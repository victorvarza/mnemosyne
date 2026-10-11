# Mnemosyne - OpenCode Memory Plugin

> ⚠️ **Educational Purpose Only**: This project is designed for educational and research purposes only. It demonstrates concepts related to AI assistant memory management and security assessment techniques. Any security testing capabilities should only be used in controlled environments with explicit authorization.

Mnemosyne is an **OpenCode plugin** that provides persistent memory capabilities for AI assistants. It enables personalized context memory workflows while keeping sensitive data local to the user's machine.

As a plugin for [OpenCode](https://opencode.ai), Mnemosyne seamlessly integrates with AI assistant workflows, automatically managing memory storage and retrieval without manual intervention. It also includes security assessment tools for analyzing source code and performing authorized penetration testing.

## OpenCode Plugin Features

As an OpenCode plugin, Mnemosyne provides:

### 🧠 Automatic Memory Management
- **Seamless Integration**: Works automatically with OpenCode assistant workflows
- **Smart Storage**: Automatically identifies and stores important conversation context
- **Memory Management Tools**: Manual `remember` and `recall` commands for explicit memory control
- **Context Retrieval**: Retrieves relevant memories when the AI responds
- **Background Operation**: Operates with minimal configuration
- **OpenCode Skills**: Ships skill instructions for memory, authorized security assessment, and Docker/Kali tool workflows under `.opencode/skill/`

### 🔒 Security Assessment Tools
- **Source Code Analysis**: Scan projects for security vulnerabilities
- **Penetration Testing**: Perform authorized pentesting against deployed applications

### 🏠 Privacy First Architecture
- **Local Memory Storage**: All memories stored in a local SQLite database
- **Client-Side Control**: Memory management happens entirely on the user's machine
- **Private Inference**: Connect to remote Ollama workers for embeddings/LLM calls only


## Architecture Overview

Mnemosyne separates inference from memory ownership, integrating seamlessly with OpenCode:

```
┌─────────────────┐    ┌──────────────────────┐
│   OpenCode      │    │  Ollama Worker       │
│   Assistant     │    │                      │
│                 │    │  ┌────────────────┐  │
│ ┌─────────────┐ │    │  │  Qwen LLM      │  │
│ │Mnemosyne    │◄┼────┼─►└────────────────┘  │
│ │Plugin       │ │    │  ┌────────────────┐  │
│ └─────────────┘ │    │  │Embedding Model │  │
│                 │    │  └────────────────┘  │
└─────────────────┘    └──────────────────────┘
                              ▲ HTTP
                              │
                    ┌─────────▼──────────┐
                    │  Local Client      │
                    │                    │
                    │  ┌─────────────┐   │
                    │  │Memory Store │   │
                    │  │(SQLite +    │   │
                    │  │ sqlite-vec) │   │
                    │  └─────────────┘   │
                    └────────────────────┘
```

The plugin performs all memory operations locally while connecting to remote
Ollama workers for embeddings and LLM inference. Use protected network access
for the worker.

## Quick Start

As an OpenCode plugin, Mnemosyne works automatically in the background. Simply install and use OpenCode normally:

1. **Install the plugin**: use `.opencode/plugins/mnemosyne` for OpenCode 2, or
   `claudecode-plugin/` for [Claude Code](https://claude.com/claude-code)
2. **Start conversing**: Mnemosyne automatically stores important context
3. **Get contextual responses**: Relevant memories are automatically retrieved

For manual control, use these plugin tools:

```bash
# Manual memory storage (when needed)
> mnemo_remember --content "User prefers Python for backend development"

# Manual memory retrieval (when needed)
> mnemo_recall --query "What programming language does the user prefer?"

# Security assessment
> mnemo_assessCreate --assessmentId web-lab --target https://my-app.example.com --authorized "Approved under ticket SEC-123"
> mnemo_pentest --assessmentId web-lab --sourcePath ./my-app --targetUrl https://my-app.example.com
> mnemo_scan --projectPath ./my-project

# Docker/Kali security tools
> mnemo_securityToolsList --category web-scan
> mnemo_securityToolRun --toolName nmap --authorization "Approved under ticket SEC-123" --args "-sV my-app.example.com"
```

See the [plugin documentation](docs/plugin.md) for detailed usage instructions.

## Documentation

- **[Architecture](docs/architecture.md)** — components, data flow, and the memory pipeline
- **[Setup and usage guide](docs/usage.md)** — worker/client setup and commands
- **[OpenCode Plugin Guide](docs/plugin.md)** — complete plugin usage and API reference
- **[Evaluation plan](docs/evaluation.md)** — benchmarks, metrics, and experiments
- **[Security assessment notes](docs/security.md)** — threat model and safeguards
