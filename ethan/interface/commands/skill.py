"""skill 子命令组：管理 Skill 文件。

命令：
  ethan skill list              列出所有已加载的 Skills
  ethan skill show <name>       查看某个 Skill 内容
  ethan skill add <源>          从 GitHub 仓库/子目录安装 Skill（支持内置别名，如 legal）
  ethan skill create <name>     创建一个新的空 Skill 文件
"""
import typer
import asyncio
from rich.console import Console
from rich.table import Table

from ethan.skills.loader import load_all_skills

console = Console()
app = typer.Typer(help="管理 Skills", invoke_without_command=True)

# 内置 Skill 别名 → GitHub 安装来源。让 `ethan skill add legal` 一键装法律技能。
SKILL_ALIASES: dict[str, str] = {
    "legal": "llm011/ethan-legal-skill/skills/legal-assistant",
}


@app.callback(invoke_without_command=True)
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command("list")
def list_skills() -> None:
    """列出所有已加载的 Skills。"""
    skills = load_all_skills()
    if not skills:
        console.print("[dim]No skills found. Add .md files to ~/.ethan/skills/[/dim]")
        return

    table = Table(title="Skills", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("Triggers", style="yellow")
    table.add_column("Description")

    for s in skills:
        table.add_row(s.name, " | ".join(s.trigger[:3]), s.description)

    console.print(table)


@app.command("show")
def show_skill(
    name: str = typer.Argument(..., help="Skill name"),
) -> None:
    """查看某个 Skill 的完整内容。"""
    skills = load_all_skills()
    for s in skills:
        if s.name == name:
            console.print(f"[bold cyan]{s.name}[/bold cyan] [dim]({s.source})[/dim]\n")
            console.print(f"[dim]Triggers:[/dim] {' | '.join(s.trigger)}")
            console.print(f"[dim]Description:[/dim] {s.description}\n")
            console.print(s.content)
            return
    console.print(f"[red]Skill '{name}' not found.[/red]")
    raise typer.Exit(1)


@app.command("add")
def add_skill(
    source: str = typer.Argument(
        ...,
        help="GitHub 来源（owner/repo 或带子目录、完整 URL），或内置别名（如 legal）",
    ),
    name: str = typer.Option("", "-n", "--name", help="装成的 skill 目录名（仓库含多个 skill 时指定）"),
) -> None:
    """从 GitHub 仓库/子目录安装 Skill 到 ~/.ethan/skills/。

    内置别名一键装：
      ethan skill add legal        # = llm011/ethan-legal-skill/skills/legal-assistant
    """
    from ethan.tools.builtin.install_skill import InstallSkillTool

    resolved = SKILL_ALIASES.get(source.strip().lower(), source)
    if resolved != source:
        console.print(f"[dim]别名 '{source}' → {resolved}[/dim]")

    with console.status(f"[dim]安装中：{resolved}…[/dim]"):
        result = asyncio.run(InstallSkillTool().run(source=resolved, name=name))
    console.print(result)


@app.command("create")
def create_skill(
    name: str = typer.Argument(..., help="Skill name (kebab-case)"),
    trigger: str = typer.Option(..., "-t", "--trigger", help="Trigger keywords separated by |"),
    description: str = typer.Option("", "-d", "--desc", help="Short description"),
) -> None:
    """创建一个新的空 Skill 文件。"""
    from ethan.core.paths import user_skills_dir

    skills_dir = user_skills_dir()
    skills_dir.mkdir(parents=True, exist_ok=True)
    path = skills_dir / f"{name}.md"

    if path.exists():
        console.print(f"[yellow]Skill '{name}' already exists at {path}[/yellow]")
        raise typer.Exit(1)

    content = f"""---
name: {name}
trigger: {trigger}
description: {description}
---

# {name}

(Edit this file to add your skill content)
"""
    path.write_text(content, encoding="utf-8")
    console.print(f"[green]✓ Created: {path}[/green]")
    console.print(f"[dim]Edit this file to add your skill content.[/dim]")
