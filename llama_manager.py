#!/usr/bin/env python3
import sys, os, subprocess, pty, re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QTextEdit, QVBoxLayout,
    QFileDialog, QLabel, QLineEdit, QHBoxLayout, QComboBox
)
from PyQt5.QtCore import QProcess, QSocketNotifier, Qt

def strip_ansi(text):
    """
    使用正则表达式过滤 ANSI 转义序列
    """
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

class CompileRunTool(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        # 用于编译与运行的 QProcess
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.onOutput)
        self.process.readyReadStandardError.connect(self.onError)

        # 用于服务端进程（编译、启动服务器、列模型、拉取模型）
        self.serverProcess = QProcess(self)
        self.serverProcess.readyReadStandardOutput.connect(self.onServerOutput)
        self.serverProcess.readyReadStandardError.connect(self.onServerError)

        # 用于列出模型的进程
        self.modelListProcess = QProcess(self)
        self.modelListProcess.readyReadStandardOutput.connect(self.onModelListOutput)
        self.modelListProcess.readyReadStandardError.connect(self.onModelListError)

        # 用于拉取模型的进程：合并标准输出和错误，避免刷屏
        self.pullProcess = QProcess(self)
        self.pullProcess.setProcessChannelMode(QProcess.MergedChannels)
        self.pullProcess.readyReadStandardOutput.connect(self.onPullOutput)

        # 使用伪终端运行所选模型的进程（交互式进程）
        self.modelPtyProcess = None
        self.modelMaster = None
        self.modelNotifier = None

    def initUI(self):
        self.setWindowTitle('ollama-gpt: 用AI迭代的程序')
        self.resize(800, 600)
        
        # ──────────────────────────────────────────────
        # 0. 仓库地址标签（可点击超链接）
        # ──────────────────────────────────────────────
        self.repoLabel = QLabel()
        self.repoLabel.setTextFormat(Qt.RichText)           # 支持富文本
        self.repoLabel.setOpenExternalLinks(True)           # 允许点击跳转外部链接
        self.repoLabel.setText(
            '<a href="https://github.com/MarsDoge/ollama-gpt">'
            '源码地址: https://github.com/MarsDoge/ollama-gpt</a>'
        )
        # 新增版本号标签（仅增加这一行）
        self.versionLabel = QLabel("版本号: v1.0.0")

        # 将仓库地址和版本号放在一个水平布局中
        repoLayout = QHBoxLayout()
        repoLayout.addWidget(self.repoLabel)
        repoLayout.addWidget(self.versionLabel)

        # ──────────────────────────────────────────────
        # 1. 源码路径选择区域，默认路径为当前目录下的ollama
        # ──────────────────────────────────────────────
        self.pathLabel = QLabel("ollama路径:")
        self.pathEdit = QLineEdit(os.path.join(os.getcwd(), "ollama"))
        self.browseButton = QPushButton("浏览")
        self.browseButton.clicked.connect(self.selectSourcePath)
        pathLayout = QHBoxLayout()
        pathLayout.addWidget(self.pathLabel)
        pathLayout.addWidget(self.pathEdit)
        pathLayout.addWidget(self.browseButton)
        
        # ──────────────────────────────────────────────
        # 2. 编译 & 一键启动服务器并列出模型 按钮区域
        # ──────────────────────────────────────────────
        self.compileButton = QPushButton('一键编译')
        self.serverListButton = QPushButton("开启服务器并列出模型")
        self.serverListButton.clicked.connect(self.startServerAndListModels)
        buttonLayout = QHBoxLayout()
        buttonLayout.addWidget(self.compileButton)
        buttonLayout.addWidget(self.serverListButton)
        
        # ──────────────────────────────────────────────
        # 3. 运行模型选择区域
        # ──────────────────────────────────────────────
        self.modelLabel = QLabel("运行模型选择:")
        self.modelComboBox = QComboBox()
        self.runSelectedModelButton = QPushButton("运行所选模型")
        self.runSelectedModelButton.clicked.connect(self.runSelectedModel)
        modelLayout = QHBoxLayout()
        modelLayout.addWidget(self.modelLabel)
        modelLayout.addWidget(self.modelComboBox)
        modelLayout.addWidget(self.runSelectedModelButton)
        
        # ──────────────────────────────────────────────
        # 4. 拉取模型区域（默认填写 deepseek-r1:7b）
        # ──────────────────────────────────────────────
        self.pullModelLabel = QLabel("拉取模型选择:")
        self.pullModelComboBox = QComboBox()
        self.pullModelComboBox.setEditable(True)
        # 默认填写 deepseek-r1:7b，并添加其它可选项
        self.pullModelComboBox.addItem("deepseek-r1:7b")
        self.pullModelComboBox.addItems(["1.5b", "7b", "13b"])
        self.pullModelButton = QPushButton("拉取所选模型")
        self.pullModelButton.clicked.connect(self.pullSelectedModel)
        pullLayout = QHBoxLayout()
        pullLayout.addWidget(self.pullModelLabel)
        pullLayout.addWidget(self.pullModelComboBox)
        pullLayout.addWidget(self.pullModelButton)
        
        # 新增一个专门显示拉取进度的标签
        self.pullProgressLabel = QLabel("")
        pullProgressLayout = QHBoxLayout()
        pullProgressLayout.addWidget(QLabel("拉取进度:"))
        pullProgressLayout.addWidget(self.pullProgressLabel)
        
        # ──────────────────────────────────────────────
        # 5. 交互命令输入区域（用于模型运行后的交互）
        # ──────────────────────────────────────────────
        self.interactiveLabel = QLabel("命令输入:")
        self.commandLineEdit = QLineEdit()
        self.commandLineEdit.returnPressed.connect(self.sendCommand)
        self.sendCommandButton = QPushButton("发送命令")
        self.sendCommandButton.clicked.connect(self.sendCommand)
        interactiveLayout = QHBoxLayout()
        interactiveLayout.addWidget(self.interactiveLabel)
        interactiveLayout.addWidget(self.commandLineEdit)
        interactiveLayout.addWidget(self.sendCommandButton)
        
        # ──────────────────────────────────────────────
        # 6. 日志输出区域：左侧服务端日志 & 右侧输出端日志
        # ──────────────────────────────────────────────
        self.serverLog = QTextEdit()
        self.serverLog.setReadOnly(True)
        self.serverLog.setPlaceholderText("服务端日志")
        self.modelLog = QTextEdit()
        self.modelLog.setReadOnly(True)
        self.modelLog.setPlaceholderText("输出端日志")
        logLayout = QHBoxLayout()
        logLayout.addWidget(self.serverLog)
        logLayout.addWidget(self.modelLog)
        
        # ──────────────────────────────────────────────
        # 7. 主布局
        # ──────────────────────────────────────────────
        mainLayout = QVBoxLayout()
        # 在最上方加上仓库地址标签
        mainLayout.addLayout(repoLayout)  # 添加仓库地址和版本号水平布局
        mainLayout.addWidget(self.versionLabel)
        mainLayout.addLayout(pathLayout)
        mainLayout.addLayout(buttonLayout)
        mainLayout.addLayout(modelLayout)
        mainLayout.addLayout(pullLayout)
        mainLayout.addLayout(pullProgressLayout)
        mainLayout.addLayout(interactiveLayout)
        mainLayout.addLayout(logLayout)
        self.setLayout(mainLayout)
        
        # 信号与槽绑定
        self.compileButton.clicked.connect(self.compileSource)

    # ──────────────────────────────────────────────
    # 选择源码路径
    # ──────────────────────────────────────────────
    def selectSourcePath(self):
        path = QFileDialog.getExistingDirectory(self, "选择源码目录", self.pathEdit.text())
        if path:
            self.pathEdit.setText(path)

    # ──────────────────────────────────────────────
    # 编译源码
    # ──────────────────────────────────────────────
    def compileSource(self):
        self.serverLog.clear()
        self.serverLog.append("开始编译...")
        source_path = self.pathEdit.text()
        self.process.start("make", ["-C", source_path])
        self.process.finished.connect(self.compileFinished)

    def onOutput(self):
        data = self.process.readAllStandardOutput().data().decode()
        data = strip_ansi(data)
        self.serverLog.append(data)

    def onError(self):
        data = self.process.readAllStandardError().data().decode()
        data = strip_ansi(data)
        self.serverLog.append("<font color='red'>" + data + "</font>")

    def compileFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.serverLog.append("编译成功!")
            self.makeExecutable()
        else:
            self.serverLog.append("编译失败!")

    def makeExecutable(self):
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            os.chmod(ollama_path, 0o755)
        else:
            self.serverLog.append(f"错误: 找不到 {ollama_path}")

    # ──────────────────────────────────────────────
    # 启动服务端
    # ──────────────────────────────────────────────
    def startServer(self):
        self.serverLog.append("启动服务端：ollama serve")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            self.makeExecutable()
            self.serverLog.append(f"服务器路径: {ollama_path}")
            working_directory = os.path.dirname(ollama_path)
            self.serverLog.append(f"设置工作目录: {working_directory}")
            self.serverProcess.setWorkingDirectory(working_directory)
            self.serverProcess.started.connect(self.onServerStarted)
            self.serverProcess.errorOccurred.connect(self.onServerErrorOccurred)
            self.serverProcess.start(f"{ollama_path}", ["serve"])
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
        self.listModels()

    def onServerStarted(self):
        self.serverLog.append("服务进程已成功启动")

    def serverFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.serverLog.append("服务端启动成功")
        else:
            self.serverLog.append(f"服务端启动失败，退出码: {exitCode}, 状态: {exitStatus}")
            error_msg = self.serverProcess.readAllStandardError().data().decode()
            error_msg = strip_ansi(error_msg)
            self.serverLog.append(f"错误信息：{error_msg}")

    def onServerOutput(self):
        data = self.serverProcess.readAllStandardOutput().data().decode()
        data = strip_ansi(data)
        self.serverLog.append("<font color='blue'>" + data + "</font>")

    def onServerError(self):
        data = self.serverProcess.readAllStandardError().data().decode()
        data = strip_ansi(data)
        self.serverLog.append("<font color='blue'>[Server Error] " + data + "</font>")

    def onServerErrorOccurred(self, error):
        self.serverLog.append(f"QProcess 错误: {error}")

    # ──────────────────────────────────────────────
    # 列出模型
    # ──────────────────────────────────────────────
    def listModels(self):
        self.serverLog.append("列出支持的模型：ollama list")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            self.makeExecutable()
            self.modelListProcess.start(f"{ollama_path}", ["list"])
        else:
            self.serverLog.append(f"错误: 找不到文件 {ollama_path}")

    def onModelListOutput(self):
        output = self.modelListProcess.readAllStandardOutput().data().decode()
        output = strip_ansi(output)
        self.serverLog.append("模型列表输出：")
        self.serverLog.append(output)
        model_names = []
        for line in output.splitlines():
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "NAME" or tokens[0].startswith("[GIN]"):
                continue
            model_names.append(tokens[0])
        if model_names:
            self.modelComboBox.clear()
            self.modelComboBox.addItems(model_names)
            self.pullModelComboBox.clear()
            self.pullModelComboBox.addItems(model_names)
        else:
            self.serverLog.append("<font color='red'>未找到有效的模型信息</font>")

    def onModelListError(self):
        error_output = self.modelListProcess.readAllStandardError().data().decode()
        error_output = strip_ansi(error_output)
        self.serverLog.append("<font color='red'>[Model List Error] " + error_output + "</font>")

    # ──────────────────────────────────────────────
    # 运行所选模型
    # ──────────────────────────────────────────────
    def runSelectedModel(self):
        selected_model = self.modelComboBox.currentText()
        if not selected_model:
            self.modelLog.append("未选择模型！")
            return
        self.modelLog.append(f"运行所选模型：ollama run {selected_model}")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if not os.path.exists(ollama_path):
            self.modelLog.append(f"错误: 找不到文件 {ollama_path}")
            return
        self.makeExecutable()
        try:
            self.modelMaster, modelSlave = os.openpty()
        except Exception as e:
            self.modelLog.append("<font color='red'>[Pty Error] 无法打开伪终端: " + str(e) + "</font>")
            return
        try:
            self.modelPtyProcess = subprocess.Popen(
                [ollama_path, "run", selected_model],
                stdin=modelSlave,
                stdout=modelSlave,
                stderr=modelSlave,
                bufsize=0,
                close_fds=True
            )
        except Exception as e:
            self.modelLog.append("<font color='red'>[Pty Error] 启动进程失败: " + str(e) + "</font>")
            os.close(modelSlave)
            os.close(self.modelMaster)
            return
        os.close(modelSlave)
        self.modelNotifier = QSocketNotifier(self.modelMaster, QSocketNotifier.Read)
        self.modelNotifier.activated.connect(self.onModelPtyOutput)
        self.modelLog.append("模型进程已启动，等待输出...")
        
    def onModelPtyOutput(self):
        try:
            output = os.read(self.modelMaster, 1024).decode()
            output = strip_ansi(output)
            if output:
                self.modelLog.append("<font color='purple'>" + output + "</font>")
            else:
                # 如果进程还在运行，暂时没有新输出；否则说明进程结束
                if self.modelPtyProcess and self.modelPtyProcess.poll() is None:
                    pass
                else:
                    self.modelLog.append("模型进程输出结束。")
                    self.modelNotifier.setEnabled(False)
        except Exception as e:
            self.modelLog.append("<font color='red'>[Pty Error] " + str(e) + "</font>")
        
    def sendCommand(self):
        cmd = self.commandLineEdit.text().strip()
        if not cmd:
            self.modelLog.append("请输入命令")
            return
        if self.modelPtyProcess is None or self.modelPtyProcess.poll() is not None:
            self.modelLog.append("模型运行进程未启动")
            return
        try:
            os.write(self.modelMaster, (cmd + "\n").encode())
            self.modelLog.append(f"发送命令: {cmd}")
            self.commandLineEdit.clear()
        except Exception as e:
            self.modelLog.append("<font color='red'>[Pty Error] 发送命令失败: " + str(e) + "</font>")

    # ──────────────────────────────────────────────
    # 拉取模型
    # ──────────────────────────────────────────────
    def pullSelectedModel(self):
        selected_model = self.pullModelComboBox.currentText()
        if not selected_model:
            self.serverLog.append("未选择要拉取的模型！")
            return
        self.serverLog.append(f"开始拉取模型：ollama pull {selected_model}")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if not os.path.exists(ollama_path):
            self.serverLog.append(f"错误: 找不到文件 {ollama_path}")
            return
        self.makeExecutable()
        self.pullProcess.setWorkingDirectory(os.path.dirname(ollama_path))
        self.pullProcess.start(f"{ollama_path}", ["pull", selected_model])
        
    def onPullOutput(self):
        data = self.pullProcess.readAllStandardOutput().data().decode()
        data = strip_ansi(data).strip()

        # 1) 如果整行包含“pulling manifest”，我们先把它去掉
        if "pulling manifest" in data:
            data = data.replace("pulling manifest", "").strip()

        # 2) 如果是进度信息（包含 "pulling" 和 "MB/"），更新进度标签
        if "pulling" in data and "MB/" in data:
            if self.pullProgressLabel.text() != data:
                self.pullProgressLabel.setText(data)
        # 3) 否则写入日志
        elif data:
            self.serverLog.append("<font color='orange'>" + data + "</font>")
        
    # ──────────────────────────────────────────────
    # 退出时清理所有子进程
    # ──────────────────────────────────────────────
    def closeEvent(self, event):
        for proc in [self.process, self.serverProcess, self.modelListProcess, self.pullProcess]:
            if proc.state() != QProcess.NotRunning:
                proc.terminate()
                proc.waitForFinished(3000)
        if self.modelPtyProcess and self.modelPtyProcess.poll() is None:
            self.modelPtyProcess.terminate()
            try:
                self.modelPtyProcess.wait(timeout=3)
            except Exception:
                self.modelPtyProcess.kill()
        event.accept()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    tool = CompileRunTool()
    tool.show()
    sys.exit(app.exec_())

