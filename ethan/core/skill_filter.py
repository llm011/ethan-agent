"""
技能过滤器 - 智能精简技能注入内容

策略：
1. 核心技能（高频）：完整注入，但压缩描述
2. 中频技能：仅注入 trigger + 简短 description (< 100 tokens)
3. 低频技能：完全移除默认注入，通过 find_tools 按需加载
4. 无用技能：直接删除
"""

from pathlib import Path
import yaml

# 核心技能列表（每次完整注入）
CORE_SKILLS = {
    "ui-card",
    "agent-browser", 
    "use-browser",
    "knowledge-search",
    "knowledge-read", 
    "knowledge-add",
    "schedule-create",
    "file-read",
    "shell",
    "web-search",
}

# 中频技能列表（仅注入简化版）
MEDIUM_SKILLS = {
    "ppt-generate",
    "paper-analysis",
    "code-review",
    "visualization",
    "getnote",
    "flomo",
    "dida",
    "qcc",
    "amap-lbs",
}

# 低频技能（不默认注入）
LOW_FREQUENCY_SKILLS = {
    "article-to-video",
    "wechat-reading",
    "jd-shopping",
    "gmail",
    "obsidian",
    "tts",
    "computer-use",
    "book-audio-digest",
    "team-manager",
}

# 废弃技能（删除）
DEPRECATED_SKILLS = {
    "苏念",
    "qa-evidence",
    "blogwatcher",
    "karpathy-wiki",
}


def compress_skill_content(skill_text: str, max_tokens: int = 200) -> str:
    """压缩技能内容，保留关键信息。"""
    lines = skill_text.split('\n')
    compressed = []
    
    for line in lines:
        # 保留 frontmatter
        if line.startswith('---'):
            compressed.append(line)
            continue
            
        # 只保留 trigger 和 description 的关键部分
        if line.strip().startswith('trigger:') or line.strip().startswith('triggers:'):
            # 提取 trigger 关键词
            trigger_part = line.split(':', 1)[1].strip()
            keywords = [k.strip() for k in trigger_part.split('|')]
            compressed.append(f"trigger: {'|'.join(keywords[:5])}")  # 最多 5 个关键词
        elif line.strip().startswith('description:'):
            # 只保留第一句话或前 100 字符
            desc_part = line.split(':', 1)[1].strip()
            if desc_part.startswith('"') or desc_part.startswith("'"):
                # 多行字符串
                end_quote = desc_part[0]
                lines_count = desc_part.count('\n') + 1
                if lines_count > 1:
                    # 取第一段
                    first_para = desc_part.split('\n\n')[0][:100]
                    compressed.append(f"description: {first_para}...")
                else:
                    compressed.append(f"description: {desc_part[:100]}...")
            else:
                compressed.append(f"description: {desc_part[:100]}...")
        elif len(compressed) < 10:  # 只保留前 10 行
            compressed.append(line)
    
    return '\n'.join(compressed)


def should_inject_skill(skill_name: str, category: str = "default") -> bool:
    """判断是否应该默认注入该技能。"""
    if skill_name in CORE_SKILLS:
        return True
    if skill_name in MEDIUM_SKILLS and category == "default":
        return False  # 中频技能不默认注入
    if skill_name in LOW_FREQUENCY_SKILLS:
        return False
    if any(deprecated in skill_name.lower() for deprecated in DEPRECATED_SKILLS):
        return False
    return False


def filter_skills(skills_dir: Path, output_dir: Path):
    """过滤技能目录，生成精简版本。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    
    for skill_dir in skills_dir.iterdir():
        if not skill_dir.is_dir():
            continue
            
        skill_name = skill_dir.name
        
        # 检查是否是废弃技能
        if any(dep in skill_name.lower() for dep in DEPRECATED_SKILLS):
            print(f"🗑️  删除废弃技能：{skill_name}")
            continue
            
        # 检查是否需要注入
        if not should_inject_skill(skill_name):
            print(f"⏭️  跳过低频技能：{skill_name}")
            continue
            
        # 读取并压缩 SKILL.md
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding='utf-8')
            compressed = compress_skill_content(content)
            
            # 写入输出目录
            output_skill_md = output_dir / skill_name / "SKILL.md"
            output_skill_md.parent.mkdir(parents=True, exist_ok=True)
            output_skill_md.write_text(compressed, encoding='utf-8')
            
            print(f"✅ 压缩技能：{skill_name} ({len(compressed)} chars)")


if __name__ == "__main__":
    from ethan.core.paths import CONFIG_DIR
    
    skills_dir = Path(__file__).parent.parent / "defaults" / "skills"
    output_dir = CONFIG_DIR / "skills"
    
    filter_skills(skills_dir, output_dir)
    print("\n✨ 技能过滤完成！")
