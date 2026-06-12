import * as fs from 'fs';

const path = 'components/chat-view.tsx';
let content = fs.readFileSync(path, 'utf8');

// Add imports
if (!content.includes('import { AllSessionsView }')) {
  content = content.replace('import { SettingsView }', 'import { AllSessionsView } from "./all-sessions-view";\nimport { SettingsView }');
}

if (!content.includes('List')) {
  content = content.replace('Calendar, Wrench } from "lucide-react";', 'Calendar, Wrench, List } from "lucide-react";');
}

// Update state type
content = content.replace(/useState<"chat" \| "settings" \| "knowledge" \| "schedule" \| "memory" \| "logs" \| "skills">/, 'useState<"chat" | "settings" | "knowledge" | "schedule" | "memory" | "logs" | "skills" | "all_sessions">');

// Update URL parsing
content = content.replace(/\["chat", "settings", "knowledge", "schedule", "memory", "skills"\]\.includes\(v\)/, '["chat", "settings", "knowledge", "schedule", "memory", "skills", "all_sessions"].includes(v)');

// Add button to sidebar
const allSessionsBtn = `
          <Button
            variant="ghost"
            className={\`w-full justify-start h-9 px-3 \${view === "all_sessions" ? "bg-accent text-accent-foreground" : "text-muted-foreground"}\`}
            onClick={() => setView("all_sessions")}
          >
            <List className="h-4 w-4 mr-2" /> 全部对话 (All Sessions)
          </Button>`;

if (!content.includes('全部对话 (All Sessions)')) {
  // Put it before 最新对话 (Recent Chats) 
  // Wait, the prompt says "ABOVE the '最新对话' (Recent Chats) section, add a new menu item"
  // Let's find " pl-6 pr-1" which contains the sessions list. Actually, it's outside the list.
  
  content = content.replace(
    /<div className="pl-6 pr-1 flex flex-col gap-1">/,
    `${allSessionsBtn}\n            <div className="pl-6 pr-1 flex flex-col gap-1">`
  );
}

// Add the view rendering
const allSessionsRender = `) : view === "all_sessions" ? (
          <AllSessionsView onSelectSession={(id) => { loadSession(id); setView("chat"); }} />
        `;

if (!content.includes('<AllSessionsView')) {
  content = content.replace(
    /\) : view === "skills" \? \(\s*<SkillsView \/>\s*\) : \(/,
    `) : view === "skills" ? (\n          <SkillsView />\n        ${allSessionsRender}) : (`
  );
}

fs.writeFileSync(path, content);
console.log("Patched chat-view.tsx");
