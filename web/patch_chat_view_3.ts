import * as fs from 'fs';

const path = 'components/chat-view.tsx';
let content = fs.readFileSync(path, 'utf8');

// The skillsRender matched next to <MemoryView />, but didn't cleanly format. Let's fix that block.
content = content.replace(
  /<MemoryView \/>\) : view === "skills" \? \(/g,
  '<MemoryView />\n        ) : view === "skills" ? ('
);

fs.writeFileSync(path, content);
console.log('Fixed spacing in components/chat-view.tsx');
