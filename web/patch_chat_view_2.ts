import * as fs from 'fs';

const path = 'components/chat-view.tsx';
let content = fs.readFileSync(path, 'utf8');

// Update the type of view state
if (content.includes('const [view, setView] = useState<"chat" | "settings" | "knowledge" | "schedule" | "memory" | "logs">("chat");')) {
  content = content.replace('const [view, setView] = useState<"chat" | "settings" | "knowledge" | "schedule" | "memory" | "logs">("chat");', 'const [view, setView] = useState<"chat" | "settings" | "knowledge" | "schedule" | "memory" | "logs" | "skills">("chat");');
}

// Add the skills button to the sidebar
const skillsButton = `
          <Button
            variant="ghost"
            className={\`w-full justify-start h-9 px-3 \${view === "skills" ? "bg-accent text-accent-foreground" : "text-muted-foreground"}\`}
            onClick={() => setView("skills")}
          >
            <Wrench className="h-4 w-4 mr-2" /> 技能 (Skills)
          </Button>`;

if (!content.includes('技能 (Skills)')) {
  content = content.replace(
    /<Button[^>]*>\s*<Clock className="h-4 w-4 mr-2" \/> 定时任务 \(Schedule\)\s*<\/Button>/,
    `$&${skillsButton}`
  );
}

// Render the skills view
const skillsRender = `) : view === "skills" ? (
          <SkillsView />`;

if (!content.includes('<SkillsView />')) {
  content = content.replace(
    /\) : view === "memory" \? \(\s*<MemoryView \/>/,
    `$&${skillsRender}`
  );
}

fs.writeFileSync(path, content);
console.log('Patched components/chat-view.tsx');
