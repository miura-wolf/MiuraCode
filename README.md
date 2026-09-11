# MiuraCode

> Your AI-Powered Dev Team, Right in Your Editor

<p align="center">
  <a href="https://github.com/miura-wolf/MiuraCode"><img src="https://img.shields.io/badge/GitHub-miura--wolf%2FMiuraCode-000000?style=flat&logo=github&logoColor=white" alt="GitHub"></a>
</p>

> **Créditos del fork:** MiuraCode es un fork comunitario de [Roo Code](https://github.com/RooCodeInc/Roo-Code) (RooCodeInc). Todo el mérito del código base pertenece al equipo y comunidad originales de Roo Code.

## What Can MiuraCode Do For YOU?

- Generate Code from natural language descriptions and specs
- Adapt with Modes: Code, Architect, Ask, Debug, and Custom Modes
- Refactor & Debug existing code
- Write & Update documentation
- Answer Questions about your codebase
- Automate repetitive tasks
- Utilize MCP Servers

## Modes

MiuraCode adapts to how you work:

- Code Mode: everyday coding, edits, and file ops
- Architect Mode: plan systems, specs, and migrations
- Ask Mode: fast answers, explanations, and docs
- Debug Mode: trace issues, add logs, isolate root causes
- Custom Modes: build specialized modes for your team or workflow

Learn more: [Using Modes](https://docs.roocode.com/basic-usage/using-modes) • [Custom Modes](https://docs.roocode.com/advanced-usage/custom-modes)

## Tutorial & Feature Videos

<div align="center">

|                                                                                                                                                                           |                                                                                                                                                                            |                                                                                                                                                                          |
| :-----------------------------------------------------------------------------------------------------------------------------------------------------------------------: | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------: | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------: |
| <a href="https://www.youtube.com/watch?v=Mcq3r1EPZ-4"><img src="https://img.youtube.com/vi/Mcq3r1EPZ-4/maxresdefault.jpg" width="100%"></a><br><b>Installing Roo Code</b> | <a href="https://www.youtube.com/watch?v=ZBML8h5cCgo"><img src="https://img.youtube.com/vi/ZBML8h5cCgo/maxresdefault.jpg" width="100%"></a><br><b>Configuring Profiles</b> | <a href="https://www.youtube.com/watch?v=r1bpod1VWhg"><img src="https://img.youtube.com/vi/r1bpod1VWhg/maxresdefault.jpg" width="100%"></a><br><b>Codebase Indexing</b>  |
|    <a href="https://www.youtube.com/watch?v=iiAv1eKOaxk"><img src="https://img.youtube.com/vi/iiAv1eKOaxk/maxresdefault.jpg" width="100%"></a><br><b>Custom Modes</b>     |     <a href="https://www.youtube.com/watch?v=Ho30nyY332E"><img src="https://img.youtube.com/vi/Ho30nyY332E/maxresdefault.jpg" width="100%"></a><br><b>Checkpoints</b>      | <a href="https://www.youtube.com/watch?v=HmnNSasv7T8"><img src="https://img.youtube.com/vi/HmnNSasv7T8/maxresdefault.jpg" width="100%"></a><br><b>Context Management</b> |

</div>
<p align="center">
<a href="https://docs.roocode.com/tutorial-videos">More quick tutorial and feature videos...</a>
</p>

## Resources

- **[GitHub Issues (MiuraCode)](https://github.com/miura-wolf/MiuraCode/issues):** Report bugs and track development of this fork.
- **[Roo Code Documentation](https://docs.roocode.com):** The upstream guide to installing, configuring, and mastering the editor (still applies to MiuraCode).
- **Upstream Roo Code community:** [Discord](https://discord.gg/roocode) • [Reddit](https://www.reddit.com/r/RooCode) • [YouTube](https://youtube.com/@roocodeyt?feature=shared) — thanks to the RooCodeInc team and community for the amazing base project.

---

## Local Setup & Development

> **New to this repo?** Read [`HANDOFF.md`](HANDOFF.md) first — it is the single
> source of truth for the whole Miura ecosystem (VS Code extension + atomic-ai
> proxy + `miura` TUI + gigaxity deep research): what was built, with evidence,
> and what to do next (Spanish, with an English TL;DR).

1. **Clone** the repo:

```sh
git clone https://github.com/miura-wolf/MiuraCode.git
```

2. **Install dependencies**:

```sh
pnpm install
```

3. **Run the extension**:

There are several ways to run the Roo Code extension:

### Development Mode (F5)

For active development, use VSCode's built-in debugging:

Press `F5` (or go to **Run** → **Start Debugging**) in VSCode. This will open a new VSCode window with the Roo Code extension running.

- Changes to the webview will appear immediately.
- Changes to the core extension will also hot reload automatically.

### Automated VSIX Installation

To build and install the extension as a VSIX package directly into VSCode:

```sh
pnpm install:vsix [-y] [--editor=<command>]
```

This command will:

- Ask which editor command to use (code/cursor/code-insiders) - defaults to 'code'
- Uninstall any existing version of the extension.
- Build the latest VSIX package.
- Install the newly built VSIX.
- Prompt you to restart VS Code for changes to take effect.

Options:

- `-y`: Skip all confirmation prompts and use defaults
- `--editor=<command>`: Specify the editor command (e.g., `--editor=cursor` or `--editor=code-insiders`)

### Manual VSIX Installation

If you prefer to install the VSIX package manually:

1.  First, build the VSIX package:
    ```sh
    pnpm vsix
    ```
2.  A `.vsix` file will be generated in the `bin/` directory (e.g., `bin/miuracode-<version>.vsix`).
3.  Install it manually using the VSCode CLI:
    ```sh
    code --install-extension bin/miuracode-<version>.vsix
    ```

---

We use [changesets](https://github.com/changesets/changesets) for versioning and publishing. Check our `CHANGELOG.md` for release notes.

---

## Disclaimer

**Please note** that Roo Code, Inc does **not** make any representations or warranties regarding any code, models, or other tools provided or made available in connection with Roo Code, any associated third-party tools, or any resulting outputs. You assume **all risks** associated with the use of any such tools or outputs; such tools are provided on an **"AS IS"** and **"AS AVAILABLE"** basis. Such risks may include, without limitation, intellectual property infringement, cyber vulnerabilities or attacks, bias, inaccuracies, errors, defects, viruses, downtime, property loss or damage, and/or personal injury. You are solely responsible for your use of any such tools or outputs (including, without limitation, the legality, appropriateness, and results thereof).

---

## Contributing

We love community contributions! Get started by reading our [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

[Apache 2.0 © 2025 Roo Code, Inc.](./LICENSE)

---

**Enjoy Roo Code!** Whether you keep it on a short leash or let it roam autonomously, we can’t wait to see what you build. If you have questions or feature ideas, drop by our [Reddit community](https://www.reddit.com/r/RooCode/) or [Discord](https://discord.gg/roocode). Happy coding!
