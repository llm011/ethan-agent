"use client";

import { useEffect, useState } from "react";
import { SkillInfo, fetchSkills, saveSkill } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { MdEditor } from "@/components/md-editor";
import { Plus, Save, Search, Wrench } from "lucide-react";

export function SkillsView() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [triggers, setTriggers] = useState("");
  const [content, setContent] = useState("");

  useEffect(() => {
    loadSkills();
  }, []);

  async function loadSkills() {
    setLoading(true);
    try {
      const data = await fetchSkills();
      setSkills(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  function handleSelect(skill: SkillInfo) {
    setSelectedSkill(skill);
    setName(skill.name);
    setDescription(skill.description || "");
    setTriggers(skill.trigger?.join(", ") || "");
    setContent(skill.content || "");
  }

  const filteredSkills = skills.filter(skill => {
    if (!searchQuery.trim()) return true;
    const q = searchQuery.toLowerCase();
    return (
      skill.name.toLowerCase().includes(q) ||
      (skill.description || "").toLowerCase().includes(q) ||
      (skill.trigger || []).some(t => t.toLowerCase().includes(q))
    );
  });

  function handleNew() {
    setSelectedSkill(null);
    setName("");
    setDescription("");
    setTriggers("");
    setContent("");
  }

  async function handleSave() {
    if (!name.trim() || !content.trim()) return;
    
    setSaving(true);
    try {
      const triggerList = triggers.split(",").map(t => t.trim()).filter(Boolean);
      await saveSkill({
        name,
        description,
        trigger: triggerList,
        content
      });
      await loadSkills();
      
      // Keep selected
      setSelectedSkill({
        name,
        description,
        trigger: triggerList,
        content
      });
    } catch (e) {
      console.error(e);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex h-full w-full bg-background border-l border-border/40">
      {/* Sidebar */}
      <div className="w-64 border-r border-border/40 flex flex-col bg-muted/10">
        <div className="p-4 border-b border-border/40 flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <Wrench className="w-4 h-4" />
            Skills
          </h2>
          <Button variant="ghost" size="icon" onClick={handleNew} title="New Skill">
            <Plus className="w-4 h-4" />
          </Button>
        </div>

        <div className="px-3 py-2 border-b border-border/40">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none" />
            <Input
              value={searchQuery}
              onChange={e => setSearchQuery(e.target.value)}
              placeholder="Search skills..."
              className="pl-8 h-8 text-sm"
            />
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-2 space-y-2">
            {loading ? (
              <div className="p-4 text-sm text-muted-foreground text-center">Loading skills...</div>
            ) : filteredSkills.length === 0 ? (
              <div className="p-4 text-sm text-muted-foreground text-center">
                {searchQuery.trim() ? "No matching skills." : "No skills found."}
              </div>
            ) : (
              filteredSkills.map(skill => (
                <div
                  key={skill.name}
                  onClick={() => handleSelect(skill)}
                  className={`p-3 rounded-lg cursor-pointer transition-colors border ${
                    selectedSkill?.name === skill.name 
                      ? 'bg-primary/10 border-primary/20' 
                      : 'hover:bg-muted border-transparent'
                  }`}
                >
                  <div className="font-medium text-sm">{skill.name}</div>
                  <div className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {skill.description || "No description"}
                  </div>
                </div>
              ))
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        <div className="p-4 border-b border-border/40 flex items-center justify-between bg-card">
          <h2 className="font-semibold">
            {selectedSkill ? `Edit Skill: ${selectedSkill.name}` : "Create New Skill"}
          </h2>
          <Button 
            onClick={handleSave} 
            disabled={saving || !name.trim() || !content.trim()}
            size="sm"
            className="gap-2"
          >
            <Save className="w-4 h-4" />
            {saving ? "Saving..." : "Save Skill"}
          </Button>
        </div>

        <ScrollArea className="flex-1 p-6">
          <div className="max-w-3xl mx-auto space-y-6 pb-20">
            <div className="space-y-4">
              <div className="grid gap-2">
                <label className="text-sm font-medium">Name</label>
                <Input 
                  value={name} 
                  onChange={e => setName(e.target.value)} 
                  placeholder="e.g. review-pr" 
                  disabled={!!selectedSkill} // Name is usually the filename, so disabling edit for now
                />
                <p className="text-xs text-muted-foreground">Unique identifier. Used as the filename.</p>
              </div>

              <div className="grid gap-2">
                <label className="text-sm font-medium">Description</label>
                <Input 
                  value={description} 
                  onChange={e => setDescription(e.target.value)} 
                  placeholder="What does this skill do?" 
                />
              </div>

              <div className="grid gap-2">
                <label className="text-sm font-medium">Triggers (comma separated)</label>
                <Input 
                  value={triggers} 
                  onChange={e => setTriggers(e.target.value)} 
                  placeholder="review, pr, review code" 
                />
                <p className="text-xs text-muted-foreground">Words or phrases that will activate this skill in conversation.</p>
              </div>

              <div className="grid gap-2">
                <label className="text-sm font-medium">内容 (Content)</label>
                <MdEditor
                  value={content}
                  onChange={setContent}
                  placeholder="Instructions for the agent..."
                />
              </div>
            </div>
          </div>
        </ScrollArea>
      </div>
    </div>
  );
}
