import * as fs from 'fs';

const path = 'components/chat-view.tsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace(
  /const \[view, setView\] = useState<"chat" \| "settings" \| "knowledge" \| "schedule" \| "memory" \| "logs" \| "skills">\| "settings" \| "knowledge" \| "schedule" \| "memory" \| "logs" \| "skills">\("chat"\);/,
  'const [view, setView] = useState<"chat" | "settings" | "knowledge" | "schedule" | "memory" | "logs" | "skills">("chat");'
);

fs.writeFileSync(path, content);
console.log('Fixed syntax error');
