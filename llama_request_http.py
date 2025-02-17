#!/usr/bin/env python3
import sys, os, re, platform, json, requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QTextEdit, QVBoxLayout,
    QFileDialog, QLabel, QLineEdit, QHBoxLayout, QComboBox, QProgressBar
)
from PyQt5.QtCore import QProcess, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor

def strip_output(text):
    """
    过滤 ANSI 转义序列和 spinner 字符（例如：⠙ ⠹ ⠸ ⠴ ⠦ ⠧ ⠇ ⠏ ⠋）
    """
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    spinner_pattern = re.compile(r'[⠙⠹⠸⠴⠦⠧⠇⠏⠋]+')
    text = spinner_pattern.sub('', text)
    return text

def get_arch_info():
    return platform.machine()

class PullThread(QThread):
    progress_signal = pyqtSignal(int)   # 进度百分比
    log_signal = pyqtSignal(str)        # 用于在UI上显示日志（拉取进度的debug信息）
    info_signal = pyqtSignal(str)       # 下载信息，如“Downloaded: ... / Total: ...”

    def __init__(self, url, payload, timeout=30, parent=None):
        super().__init__(parent)
        self.url = url
        self.payload = payload
        self.timeout = timeout
        self._running = True

    def run(self):
        try:
            response = requests.post(self.url, json=self.payload, timeout=self.timeout, stream=True)
            self.progress_signal.emit(0)
            for line in response.iter_lines():
                if not self._running:
                    break
                if line:
                    decoded_line = line.decode('utf-8').strip()
                    # 输出调试信息
                    self.log_signal.emit("<font color='orange'>DEBUG: " + decoded_line + "</font>")
                    # 尝试解析 JSON 格式进度信息
                    try:
                        obj = json.loads(decoded_line)
                        if "total" in obj and "completed" in obj:
                            total = int(obj["total"])
                            completed = int(obj["completed"])
                            if total > 0:
                                progress = int((completed / total) * 100)
                                self.progress_signal.emit(progress)
                                self.info_signal.emit(f"Downloaded: {completed} bytes / Total: {total} bytes")
                    except Exception:
                        # 如果 JSON 解析失败，尝试正则匹配（根据实际返回格式调整）
                        match = re.search(r'Downloaded:\s*(\d+).*Total:\s*(\d+)', decoded_line)
                        if match:
                            completed = int(match.group(1))
                            total = int(match.group(2))
                            if total > 0:
                                progress = int((completed / total) * 100)
                                self.progress_signal.emit(progress)
                                self.info_signal.emit(f"Downloaded: {completed} bytes / Total: {total} bytes")
            self.progress_signal.emit(100)
        except Exception as e:
            self.log_signal.emit(f"拉取模型异常：{e}")

    def stop(self):
        self._running = False

class GenerateThread(QThread):
    """
    该线程调用 /api/generate 接口，并将每行输出都视为原始输出，通过 raw_signal 发给UI；
    如果能解析出 JSON 且包含 "response" 字段，则仅把 "response" 的内容视为「有效数据」发给 model_signal。
    """
    raw_signal = pyqtSignal(str)     # 原始输出信号
    model_signal = pyqtSignal(str)   # 仅包含有效数据的信号
    log_signal = pyqtSignal(str)     # 其他日志信息

    def __init__(self, url, payload, timeout=30, parent=None):
        super().__init__(parent)
        self.url = url
        self.payload = payload
        self.timeout = timeout
        self._running = True

    def run(self):
        try:
            response = requests.post(self.url, json=self.payload, timeout=self.timeout, stream=True)
            for line in response.iter_lines():
                if not self._running:
                    break
                if line:
                    decoded_line = line.decode('utf-8').strip()
                    # 将每一行都当作原始输出
                    self.raw_signal.emit(decoded_line)

                    # 如果这一行能被JSON解析，且包含"response"，就把"response"视为有效数据
                    try:
                        obj = json.loads(decoded_line)
                        if "response" in obj:
                            # 只显示 obj["response"] 作为有效数据
                            self.model_signal.emit(obj["response"])
                    except Exception:
                        pass

            self.log_signal.emit("生成完成。")
        except Exception as e:
            self.log_signal.emit(f"生成异常：{e}")

    def stop(self):
        self._running = False

class CompileRunTool(QWidget):
    def __init__(self):
        super().__init__()
        self.pullThread = None       # 用于拉取模型的线程
        self.generateThread = None   # 用于生成模型回复的线程
        self.initUI()

        # 用于编译的 QProcess
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.onOutput)
        self.process.readyReadStandardError.connect(self.onError)

        # 用于启动服务器的 QProcess
        self.serverProcess = QProcess(self)
        self.serverProcess.readyReadStandardOutput.connect(self.onServerOutput)
        self.serverProcess.readyReadStandardError.connect(self.onServerError)

        # 用于列出模型的 QProcess（备用，主要使用 API）
        self.modelListProcess = QProcess(self)
        self.modelListProcess.readyReadStandardOutput.connect(self.onModelListOutput)
        self.modelListProcess.readyReadStandardError.connect(self.onModelListError)
        self.modelPtyProcess = None

    def initUI(self):
        self.setWindowTitle('ollama-gpt: 用AI迭代的程序')
        self.resize(900, 600)
        
        # 0. 仓库地址与版本号
        self.repoLabel = QLabel()
        self.repoLabel.setTextFormat(Qt.RichText)
        self.repoLabel.setOpenExternalLinks(True)
        self.repoLabel.setText(
            '<a href="https://github.com/MarsDoge/ollama-gpt">'
            '源码地址: https://github.com/MarsDoge/ollama-gpt</a>'
        )
        self.versionLabel = QLabel("版本号: v1.0.0")
        repoLayout = QHBoxLayout()
        repoLayout.addWidget(self.repoLabel)
        repoLayout.addWidget(self.versionLabel)
        
        # 0.1 架构信息
        self.archLabel = QLabel("架构: " + get_arch_info())
        
        # 1. 源码路径选择区域
        self.pathLabel = QLabel("ollama路径:")
        self.pathEdit = QLineEdit(os.path.join(os.getcwd(), "ollama"))
        self.browseButton = QPushButton("浏览")
        self.browseButton.clicked.connect(self.selectSourcePath)
        pathLayout = QHBoxLayout()
        pathLayout.addWidget(self.pathLabel)
        pathLayout.addWidget(self.pathEdit)
        pathLayout.addWidget(self.browseButton)
        
        # 2. 编译 & 一键启动服务器并列出模型
        self.compileButton = QPushButton('一键编译')
        self.serverListButton = QPushButton("开启服务器并列出模型")
        self.serverListButton.clicked.connect(self.startServerAndListModels)
        buttonLayout = QHBoxLayout()
        buttonLayout.addWidget(self.compileButton)
        buttonLayout.addWidget(self.serverListButton)
        
        # 3. 运行模型选择区域
        self.modelLabel = QLabel("运行模型选择:")
        self.modelComboBox = QComboBox()
        self.runSelectedModelButton = QPushButton("运行所选模型")
        self.runSelectedModelButton.clicked.connect(self.runSelectedModel)
        modelLayout = QHBoxLayout()
        modelLayout.addWidget(self.modelLabel)
        modelLayout.addWidget(self.modelComboBox)
        modelLayout.addWidget(self.runSelectedModelButton)
        
        # 4. 拉取模型区域
        self.pullModelLabel = QLabel("拉取模型选择:")
        self.pullModelComboBox = QComboBox()
        self.pullModelComboBox.setEditable(True)
        self.pullModelComboBox.addItem("deepseek-r1:7b")
        self.pullModelComboBox.addItems(["1.5b", "7b", "13b"])
        self.pullModelButton = QPushButton("拉取所选模型")
        self.pullModelButton.clicked.connect(self.pullSelectedModel)
        pullLayout = QHBoxLayout()
        pullLayout.addWidget(self.pullModelLabel)
        pullLayout.addWidget(self.pullModelComboBox)
        pullLayout.addWidget(self.pullModelButton)
        
        # 4.1 进度条和信息标签显示拉取进度
        self.progressBar = QProgressBar()
        self.progressBar.setRange(0, 100)
        self.progressInfoLabel = QLabel("Downloaded: 0 bytes / Total: 0 bytes")
        progressLayout = QHBoxLayout()
        progressLayout.addWidget(QLabel("拉取进度:"))
        progressLayout.addWidget(self.progressBar)
        progressLayout.addWidget(self.progressInfoLabel)
        
        # 5. 交互命令输入区域
        self.interactiveLabel = QLabel("命令输入:")
        self.commandLineEdit = QLineEdit()
        self.commandLineEdit.returnPressed.connect(self.sendCommand)
        self.sendCommandButton = QPushButton("发送命令")
        self.sendCommandButton.clicked.connect(self.sendCommand)
        interactiveLayout = QHBoxLayout()
        interactiveLayout.addWidget(self.interactiveLabel)
        interactiveLayout.addWidget(self.commandLineEdit)
        interactiveLayout.addWidget(self.sendCommandButton)
        
        # 6. 三列日志输出区域
        #    左侧：服务端日志（serverLog）
        #    中间：原始输出（rawLog）
        #    右侧：客户端输出（modelLog）只显示有效数据
        self.serverLog = QTextEdit()
        self.serverLog.setReadOnly(True)
        self.serverLog.setPlaceholderText("服务端日志")
        
        self.rawLog = QTextEdit()
        self.rawLog.setReadOnly(True)
        self.rawLog.setPlaceholderText("原始输出")
        
        self.modelLog = QTextEdit()
        self.modelLog.setReadOnly(True)
        self.modelLog.setPlaceholderText("客户端输出(有效数据)")
        
        logLayout = QHBoxLayout()
        logLayout.addWidget(self.serverLog)
        logLayout.addWidget(self.rawLog)
        logLayout.addWidget(self.modelLog)
        
        # 主布局组装
        mainLayout = QVBoxLayout()
        mainLayout.addLayout(repoLayout)
        mainLayout.addWidget(self.archLabel)
        mainLayout.addLayout(pathLayout)
        mainLayout.addLayout(buttonLayout)
        mainLayout.addLayout(modelLayout)
        mainLayout.addLayout(pullLayout)
        mainLayout.addLayout(progressLayout)
        mainLayout.addLayout(interactiveLayout)
        mainLayout.addLayout(logLayout)
        self.setLayout(mainLayout)
        
        self.compileButton.clicked.connect(self.compileSource)

    def selectSourcePath(self):
        path = QFileDialog.getExistingDirectory(self, "选择源码目录", self.pathEdit.text())
        if path:
            self.pathEdit.setText(path)

    def get_ollama_path(self):
        source_path = self.pathEdit.text()
        exe_name = "ollama.exe" if os.name == "nt" else "ollama"
        return os.path.join(source_path, exe_name)
    
    def compileSource(self):
        self.serverLog.clear()
        self.serverLog.append("开始编译...")
        source_path = self.pathEdit.text()
        if os.name == 'nt':
            self.process.start("mingw32-make", ["-C", source_path])
        else:
            self.process.start("make", ["-C", source_path])
        self.process.finished.connect(self.compileFinished)

    def onOutput(self):
        data = self.process.readAllStandardOutput().data().decode()
        data = strip_output(data)
        self.serverLog.append(data)

    def onError(self):
        data = self.process.readAllStandardError().data().decode()
        data = strip_output(data)
        self.serverLog.append("<font color='red'>" + data + "</font>")

    def compileFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.serverLog.append("编译成功!")
            self.makeExecutable()
        else:
            self.serverLog.append("编译失败!")

    def makeExecutable(self):
        if os.name != "nt":
            ollama_path = self.get_ollama_path()
            if os.path.exists(ollama_path):
                os.chmod(ollama_path, 0o755)
            else:
                self.serverLog.append(f"错误: 找不到 {ollama_path}")

    def startServer(self):
        self.serverLog.append("启动服务端：ollama serve")
        ollama_path = self.get_ollama_path()
        if os.path.exists(ollama_path):
            self.makeExecutable()
            self.serverLog.append(f"服务器路径: {ollama_path}")
            working_directory = os.path.dirname(ollama_path)
            self.serverLog.append(f"设置工作目录: {working_directory}")
            self.serverProcess.setWorkingDirectory(working_directory)
            self.serverProcess.started.connect(self.onServerStarted)
            self.serverProcess.errorOccurred.connect(self.onServerErrorOccurred)
            self.serverProcess.start(ollama_path, ["serve"])
            if not self.serverProcess.waitForStarted(3000):
                self.serverLog.append("启动进程失败！")
                return
            self.serverProcess.finished.connect(self.serverFinished)
            self.serverProcess.readyReadStandardError.connect(self.onServerError)
            self.serverProcess.readyReadStandardOutput.connect(self.onServerOutput)
        else:
            self.serverLog.append(f"错误: 找不到文件 {ollama_path}")

    def startServerAndListModels(self):
        self.startServer()
        QProcess().startDetached("sleep", ["2"])
        self.listModels()

    def onServerStarted(self):
        self.serverLog.append("服务进程已成功启动")

    def serverFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.serverLog.append("服务端启动成功")
        else:
            self.serverLog.append(f"服务端启动失败，退出码: {exitCode}, 状态: {exitStatus}")
            error_msg = self.serverProcess.readAllStandardError().data().decode()
            error_msg = strip_output(error_msg)
            self.serverLog.append(f"错误信息：{error_msg}")

    def onServerOutput(self):
        data = self.serverProcess.readAllStandardOutput().data().decode()
        data = strip_output(data)
        self.serverLog.append("<font color='blue'>" + data + "</font>")

    def onServerError(self):
        data = self.serverProcess.readAllStandardError().data().decode()
        data = strip_output(data)
        self.serverLog.append("<font color='blue'>[Server Error] " + data + "</font>")

    def onServerErrorOccurred(self, error):
        self.serverLog.append(f"QProcess 错误: {error}")

    # ---------------- API 调用部分 ----------------
    def listModels(self):
        self.serverLog.append("通过 API 列出支持的模型...")
        url = "http://localhost:11434/api/tags"
        try:
            response = requests.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                models = [m["name"] for m in data.get("models", [])]
                self.serverLog.append("模型列表：" + ", ".join(models))
                self.modelComboBox.clear()
                self.modelComboBox.addItems(models)
                self.pullModelComboBox.clear()
                self.pullModelComboBox.addItems(models)
            else:
                self.serverLog.append(f"列模型失败，状态码：{response.status_code}")
        except Exception as e:
            self.serverLog.append(f"列模型异常：{e}")

    def onModelListOutput(self):
        output = self.modelListProcess.readAllStandardOutput().data().decode()
        output = strip_output(output)
        self.serverLog.append("模型列表输出：")
        self.serverLog.append(output)

    def onModelListError(self):
        error_output = self.modelListProcess.readAllStandardError().data().decode()
        error_output = strip_output(error_output)
        self.serverLog.append("<font color='red'>[Model List Error] " + error_output + "</font>")

    def pullSelectedModel(self):
        selected_model = self.pullModelComboBox.currentText()
        if not selected_model:
            self.serverLog.append("未选择要拉取的模型！")
            return
        self.serverLog.append(f"开始拉取模型：{selected_model}（通过 API 调用）")
        url = "http://localhost:11434/api/pull"
        payload = {"name": selected_model, "stream": True}
        # 如果之前有拉取线程在运行，则先停止它
        if self.pullThread is not None and self.pullThread.isRunning():
            self.pullThread.stop()
            self.pullThread.wait()
        self.pullThread = PullThread(url, payload, timeout=30)
        self.pullThread.progress_signal.connect(self.progressBar.setValue)
        self.pullThread.info_signal.connect(self.progressInfoLabel.setText)
        self.pullThread.log_signal.connect(lambda msg: self.serverLog.append(msg))
        self.pullThread.start()

    def runSelectedModel(self):
        """
        通过 GenerateThread 实现流式输出。所有原始行存入 rawLog，若能解析出 JSON 且含 'response' 则存入 modelLog
        """
        selected_model = self.modelComboBox.currentText()
        if not selected_model:
            self.modelLog.append("未选择模型！")
            return
        prompt_text = self.commandLineEdit.text().strip()
        if not prompt_text:
            self.modelLog.append("请输入交互命令（prompt）！")
            return
        self.modelLog.append(f"调用 API 模型 {selected_model}，生成回复 (实时输出)...")
        url = "http://localhost:11434/api/generate"
        payload = {
            "model": selected_model,
            "prompt": prompt_text,
            "stream": True  # 流式输出
        }
        # 如果有旧的生成线程，先停止
        if self.generateThread is not None and self.generateThread.isRunning():
            self.generateThread.stop()
            self.generateThread.wait()
        self.generateThread = GenerateThread(url, payload, timeout=30)
        # 原始数据输出到 rawLog
        self.generateThread.raw_signal.connect(lambda line: self.rawLog.append(line))
        # 只显示 "response" 字段的文本到 modelLog
        self.generateThread.model_signal.connect(lambda text: self.modelLog.append(text))
        # 其他日志信息
        self.generateThread.log_signal.connect(lambda text: self.modelLog.append(text))
        self.generateThread.start()

    def sendCommand(self):
        self.runSelectedModel()
        self.commandLineEdit.clear()

    def closeEvent(self, event):
        for proc in [self.process, self.serverProcess, self.modelListProcess]:
            if proc.state() != QProcess.NotRunning:
                proc.terminate()
                proc.waitForFinished(3000)
        if self.pullThread is not None and self.pullThread.isRunning():
            self.pullThread.stop()
            self.pullThread.wait()
        if self.generateThread is not None and self.generateThread.isRunning():
            self.generateThread.stop()
            self.generateThread.wait()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    tool = CompileRunTool()
    tool.show()
    sys.exit(app.exec_())

