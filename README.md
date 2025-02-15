# ollama-gpt

ollama-gpt is a graphical interface tool designed to simplify the management and evolution of your ollama projects. The project is developed using GPT-o3, which drives continuous code optimization, enhanced documentation, and smarter testing processes. This innovative approach aims to transform the tool into a self-improving system that adapts to evolving development needs and industry trends.

## Features

- **One-Click Compilation:** Compile the source code effortlessly using the integrated build system.
- **Execution:** Run the compiled executable with a single click for quick testing.
- **Server Mode:** Start the server (`ollama serve`) for deployment and debugging.
- **Client Chat Interaction:** Launch the chat interaction mode (`ollama chat`) using the default 1.5b model.
- **Model Management:** List and select supported models via an interactive interface.
- **Interactive Command Input:** Send real-time commands to interact with the running model.
- **GPT-o3 Driven Development:** Leverage GPT-o3 to continuously analyze and optimize the codebase, documentation, and testing procedures.

## Prerequisites

- **Essential Tools:** Ensure you have the required tools installed for building and running the project (e.g., a compatible build system and command-line environment).
- **ollama Source Code:** The project directory should include the `ollama` folder and its related files.
- **Optional Dependencies:** While not strictly required, additional libraries such as PyQt5 can enhance the graphical interface experience.

## Installation and Usage

### 1. Clone the Repository

git clone https://github.com/MarsDoge/ollama-gpt.git
cd ollama-gpt

### 2. Install Optional Dependencies

For an enhanced GUI experience, install PyQt5 (optional):
pip install PyQt5

### 3. Project Structure

The repository contains the following files and folders:
* llama_manager.py: The main program file providing the GUI and core functionalities.
* run.sh: A startup script that checks for the required environment and launches the main program.
* ollama/: A folder containing the necessary ollama source files and resources.

### 4. Launch the Application

Run the startup script:
- ./run.sh

### 5. User Guide

* Select Source Path: Click the "Browse" button to select the directory containing the ollama source code.
* Compile the Source: Click the "One-Click Compilation" button to compile the source code using the integrated build system. The "Run" button will become active upon successful compilation.
* Run the Program: Click the "Run" button to start the application.
* Server/Client Modes: Use the "Start Server" and "Start Client Chat Interaction" buttons to launch the respective modes.
* Model Management: Click the "List Supported Models" button to display available models. Select a model from the dropdown and click "Run Selected Model" to start an interactive session. Use the command input box to send real-time commands.

## GPT-o3 Driven Development


