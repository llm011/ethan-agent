# Ethan Agent Default Skills - License & Source Attribution

This directory contains skills bundled with Ethan Agent. Each skill directory
may have its own `LICENSE` and/or `NOTICE.md` for third-party attributions.

## Project License

The Ethan Agent project is MIT-licensed (see root `LICENSE`).
All self-maintained skills inherit this MIT license unless otherwise noted
in their `SKILL.md` frontmatter.

## Third-Party Skills

| Skill | Source | License | Notes |
|---|---|---|---|
| notebooklm | https://github.com/PleasePrompto/notebooklm-skill | MIT | v1.3.0, upstream LICENSE retained |
| excalidraw | https://github.com/axtonliu/axton-obsidian-visual-skills + https://github.com/coleam00/excalidraw-diagram-skill | MIT + NO LICENSE | See `excalidraw/NOTICE.md` for risk assessment |
| gws-gmail | https://github.com/googleworkspace/cli (gws CLI) | Apache-2.0 (unconfirmed) | Skill wraps the gws CLI; CLI license applies to binary, skill code is project MIT |
| hsk-deploy | https://hsk.oray.com/doc/cli-setup.md (@aweray/hsk-cli) | 花生壳服务 ToS | Skill wraps the hsk-cli npm package; CLI license applies to binary, 花生壳服务 ToS 管控数据流，skill 代码为项目 MIT |
| archify | https://github.com/tt-a1i/archify | MIT | v2.16; runtime source NOT vendored — `install.sh` fetches from upstream at install time (see `archify/SKILL.md`); JSON-IR architecture/workflow/sequence/dataflow/lifecycle diagram renderer |

## Self-Maintained Skills (project MIT)

- vercel-deploy
- feishu-writer
- rss-briefing
- eigenflux (service: https://www.eigenflux.ai, subject to service ToS for broadcasts)
- didi-ride
- arxiv
- paper-analysis
- xiaohongshu (Python CDP engine borrowed from community, upstream unclear)
- obsidian
- bookshelf-management (not in repo; only in `~/.ethan/skills/`)

## License Review Notes

1. **MIT License**: Permissive. Must retain copyright + permission notice. Compatible with closed-source use.
2. **Apache 2.0**: Permissive + patent grant. Must retain NOTICE + license text.
3. **No License**: Default "All Rights Reserved". Technically cannot use without
   explicit permission. Risk varies by author intent.
4. **Service ToS**: For skills that wrap a SaaS (e.g. eigenflux), the service's
   Terms of Service govern data flow; skill code itself is project MIT.

For skills with unclear upstream licensing, treat as project MIT for code, but
respect any third-party trademarks/ToS for the underlying service.
