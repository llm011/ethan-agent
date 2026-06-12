import * as fs from 'fs';

const path = 'components/chat-view.tsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace('Clock, Database, Calendar, Wrench } from "lucide-react";', 'Clock, Database, Calendar, Wrench, List } from "lucide-react";');

fs.writeFileSync(path, content);
