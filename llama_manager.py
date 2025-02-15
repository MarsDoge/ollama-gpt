#!/usr/bin/env python3
import sys, os, subprocess, pty, re
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QTextEdit, QVBoxLayout,
    QFileDialog, QLabel, QLineEdit, QHBoxLayout, QComboBox
)
from PyQt5.QtCore import QProcess, QSocketNotifier

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
        # 用于服务端进程
        self.serverProcess = QProcess(self)
        self.serverProcess.readyReadStandardOutput.connect(self.onServerOutput)
        self.serverProcess.readyReadStandardError.connect(self.onServerError)
        # 用于客户端进程
        self.clientProcess = QProcess(self)
        self.clientProcess.readyReadStandardOutput.connect(self.onClientOutput)
        self.clientProcess.readyReadStandardError.connect(self.onClientError)
        # 用于列出模型的进程
        self.modelListProcess = QProcess(self)
        self.modelListProcess.readyReadStandardOutput.connect(self.onModelListOutput)
        self.modelListProcess.readyReadStandardError.connect(self.onModelListError)
        # 使用伪终端运行选中模型的进程（交互式进程）
        self.modelPtyProcess = None
        self.modelMaster = None
        self.modelNotifier = None

    def initUI(self):
        self.setWindowTitle('llama 编译与运行工具')
        self.resize(700, 600)
        
        # 源码路径选择区域
        self.pathLabel = QLabel("源码路径:")
        self.pathEdit = QLineEdit(os.path.join(os.getcwd(), "ollama")) # 根据实际情况修改默认路径
        self.browseButton = QPushButton("浏览")
        self.browseButton.clicked.connect(self.selectSourcePath)
        
        pathLayout = QHBoxLayout()
        pathLayout.addWidget(self.pathLabel)
        pathLayout.addWidget(self.pathEdit)
        pathLayout.addWidget(self.browseButton)
        
        # 编译、运行、服务端、客户端按钮区域
        self.compileButton = QPushButton('一键编译')
        self.runButton = QPushButton('运行')
        self.runButton.setEnabled(False)  # 初始状态不可用
        
        self.serverButton = QPushButton("开启服务端")
        self.clientButton = QPushButton("开启客户端聊天交互")
        
        buttonLayout = QHBoxLayout()
        buttonLayout.addWidget(self.compileButton)
        buttonLayout.addWidget(self.runButton)
        buttonLayout.addWidget(self.serverButton)
        buttonLayout.addWidget(self.clientButton)
        
        # 模型选择区域
        self.modelLabel = QLabel("模型选择:")
        self.modelComboBox = QComboBox()
        self.listModelsButton = QPushButton("列出支持的模型")
        self.listModelsButton.clicked.connect(self.listModels)
        self.runSelectedModelButton = QPushButton("运行所选模型")
        self.runSelectedModelButton.clicked.connect(self.runSelectedModel)
        
        modelLayout = QHBoxLayout()
        modelLayout.addWidget(self.modelLabel)
        modelLayout.addWidget(self.modelComboBox)
        modelLayout.addWidget(self.listModelsButton)
        modelLayout.addWidget(self.runSelectedModelButton)
        
        # 交互命令输入区域（用于运行模型后的交互）
        self.interactiveLabel = QLabel("命令输入:")
        self.commandLineEdit = QLineEdit()
        self.commandLineEdit.returnPressed.connect(self.sendCommand)  # 按回车时发送命令
        self.sendCommandButton = QPushButton("发送命令")
        self.sendCommandButton.clicked.connect(self.sendCommand)
        interactiveLayout = QHBoxLayout()
        interactiveLayout.addWidget(self.interactiveLabel)
        interactiveLayout.addWidget(self.commandLineEdit)
        interactiveLayout.addWidget(self.sendCommandButton)
        
        # 日志输出区域
        self.logText = QTextEdit()
        self.logText.setReadOnly(True)
        
        # 主布局
        layout = QVBoxLayout()
        layout.addLayout(pathLayout)
        layout.addLayout(buttonLayout)
        layout.addLayout(modelLayout)
        layout.addLayout(interactiveLayout)
        layout.addWidget(self.logText)
        self.setLayout(layout)
        
        # 信号与槽绑定
        self.compileButton.clicked.connect(self.compileSource)
        self.runButton.clicked.connect(self.runExecutable)
        self.serverButton.clicked.connect(self.startServer)
        self.clientButton.clicked.connect(self.startClient)

    def selectSourcePath(self):
        path = QFileDialog.getExistingDirectory(self, "选择源码目录", self.pathEdit.text())
        if path:
            self.pathEdit.setText(path)

    def compileSource(self):
        self.logText.clear()
        self.logText.append("开始编译...")
        source_path = self.pathEdit.text()
        self.process.start("make", ["-C", source_path])
        self.process.finished.connect(self.compileFinished)

    def onOutput(self):
        data = self.process.readAllStandardOutput().data().decode()
        data = strip_ansi(data)
        self.logText.append(data)

    def onError(self):
        data = self.process.readAllStandardError().data().decode()
        data = strip_ansi(data)
        self.logText.append("<font color='red'>" + data + "</font>")

    def compileFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.logText.append("编译成功!")
            self.runButton.setEnabled(True)
            self.makeExecutable()
        else:
            self.logText.append("编译失败!")
            self.runButton.setEnabled(False)

    def makeExecutable(self):
        """确保 ollama 文件具有执行权限"""
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            os.chmod(ollama_path, 0o755)
        else:
            self.logText.append(f"错误: 找不到 {ollama_path}")

    def runExecutable(self):
        self.logText.append("运行程序...")
        source_path = self.pathEdit.text()
        executable = os.path.join(source_path, "ollama")
        self.process.start(f"./{executable}")

    def startServer(self):
        self.logText.append("启动服务端：ollama serve")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            self.makeExecutable()
            self.logText.append(f"服务器路径: {ollama_path}")
            working_directory = os.path.dirname(ollama_path)
            self.logText.append(f"设置工作目录: {working_directory}")
            self.serverProcess.setWorkingDirectory(working_directory)
            self.serverProcess.started.connect(self.onServerStarted)
            self.serverProcess.errorOccurred.connect(self.onServerErrorOccurred)
            self.serverProcess.start(f"{ollama_path}", ["serve"])
            if not self.serverProcess.waitForStarted(3000):
                self.logText.append("启动进程失败！")
                return
            self.serverProcess.finished.connect(self.serverFinished)
            self.serverProcess.readyReadStandardError.connect(self.onServerError)
            self.serverProcess.readyReadStandardOutput.connect(self.onServerOutput)
        else:
            self.logText.append(f"错误: 找不到文件 {ollama_path}")

    def onServerStarted(self):
        self.logText.append("服务进程已成功启动")

    def serverFinished(self, exitCode, exitStatus):
        if exitCode == 0:
            self.logText.append("服务端启动成功")
        else:
            self.logText.append(f"服务端启动失败，退出码: {exitCode}, 状态: {exitStatus}")
            error_msg = self.serverProcess.readAllStandardError().data().decode()
            error_msg = strip_ansi(error_msg)
            self.logText.append(f"错误信息：{error_msg}")

    def onServerOutput(self):
        data = self.serverProcess.readAllStandardOutput().data().decode()
        data = strip_ansi(data)
        self.logText.append("<font color='blue'>" + data + "</font>")

    def onServerError(self):
        data = self.serverProcess.readAllStandardError().data().decode()
        data = strip_ansi(data)
        self.logText.append("<font color='blue'>[Server Error] " + data + "</font>")

    def onServerErrorOccurred(self, error):
        self.logText.append(f"QProcess 错误: {error}")

    def startClient(self):
        self.logText.append("启动客户端聊天交互，使用 1.5b 模型")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        self.logText.append(f"客户端路径: {ollama_path}")
        self.makeExecutable()
        self.clientProcess.start(f"./{ollama_path}", ["chat", "--model", "1.5b"])

    def onClientOutput(self):
        data = self.clientProcess.readAllStandardOutput().data().decode()
        data = strip_ansi(data)
        self.logText.append("<font color='green'>" + data + "</font>")

    def onClientError(self):
        data = self.clientProcess.readAllStandardError().data().decode()
        data = strip_ansi(data)
        self.logText.append("<font color='green'>[Client Error] " + data + "</font>")

    def listModels(self):
        self.logText.append("列出支持的模型：ollama list")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if os.path.exists(ollama_path):
            self.makeExecutable()
            self.modelListProcess.start(f"{ollama_path}", ["list"])
        else:
            self.logText.append(f"错误: 找不到文件 {ollama_path}")

    def onModelListOutput(self):
        output = self.modelListProcess.readAllStandardOutput().data().decode()
        output = strip_ansi(output)
        self.logText.append("模型列表输出：")
        self.logText.append(output)
        model_names = []
        # 解析输出，忽略标题行和无效信息（例如包含 [GIN] 的行）
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
        else:
            self.logText.append("<font color='red'>未找到有效的模型信息</font>")

    def onModelListError(self):
        error_output = self.modelListProcess.readAllStandardError().data().decode()
        error_output = strip_ansi(error_output)
        self.logText.append("<font color='red'>[Model List Error] " + error_output + "</font>")

    def runSelectedModel(self):
        selected_model = self.modelComboBox.currentText()
        if not selected_model:
            self.logText.append("未选择模型！")
            return
        self.logText.append(f"运行所选模型：ollama run {selected_model}")
        source_path = self.pathEdit.text()
        ollama_path = os.path.join(source_path, "ollama")
        if not os.path.exists(ollama_path):
            self.logText.append(f"错误: 找不到文件 {ollama_path}")
            return
        self.makeExecutable()
        
        # 使用伪终端启动交互式模型进程
        try:
            self.modelMaster, modelSlave = os.openpty()
        except Exception as e:
            self.logText.append("<font color='red'>[Pty Error] 无法打开伪终端: " + str(e) + "</font>")
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
            self.logText.append("<font color='red'>[Pty Error] 启动进程失败: " + str(e) + "</font>")
            os.close(modelSlave)
            os.close(self.modelMaster)
            return
        
        os.close(modelSlave)  # 子进程不再需要该描述符
        
        # 创建 QSocketNotifier 用于读取伪终端输出
        self.modelNotifier = QSocketNotifier(self.modelMaster, QSocketNotifier.Read)
        self.modelNotifier.activated.connect(self.onModelPtyOutput)
        self.logText.append("模型进程已启动，等待输出...")
    
    def onModelPtyOutput(self):
        try:
            output = os.read(self.modelMaster, 1024).decode()
            output = strip_ansi(output)
            if output:
                self.logText.append("<font color='purple'>" + output + "</font>")
            else:
                # 如果进程仍在运行，则不禁用 notifier
                if self.modelPtyProcess and self.modelPtyProcess.poll() is None:
                    # 进程未退出，可能只是当前没有输出
                    pass
                else:
                    self.logText.append("模型进程输出结束。")
                    self.modelNotifier.setEnabled(False)
        except Exception as e:
            self.logText.append("<font color='red'>[Pty Error] " + str(e) + "</font>")
    
    def sendCommand(self):
        cmd = self.commandLineEdit.text().strip()
        if not cmd:
            self.logText.append("请输入命令")
            return
        if self.modelPtyProcess is None or self.modelPtyProcess.poll() is not None:
            self.logText.append("模型运行进程未启动")
            return
        try:
            os.write(self.modelMaster, (cmd + "\n").encode())
            self.logText.append(f"发送命令: {cmd}")
            self.commandLineEdit.clear()
        except Exception as e:
            self.logText.append("<font color='red'>[Pty Error] 发送命令失败: " + str(e) + "</font>")

    def closeEvent(self, event):
        """退出时清理所有子进程"""
        # 清理所有 QProcess 启动的子进程
        for proc in [self.process, self.serverProcess, self.clientProcess, self.modelListProcess]:
            if proc.state() != QProcess.NotRunning:
                proc.terminate()
                proc.waitForFinished(3000)
        # 清理通过 subprocess.Popen 启动的模型进程
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

