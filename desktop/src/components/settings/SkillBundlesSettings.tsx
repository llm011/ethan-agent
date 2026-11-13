/**
 * 技能包设置组件 - 场景化技能管理
 */

import React, { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";

interface SkillBundle {
  name: string;
  description: string;
  maxTokens: number;
  autoEnable: boolean;
  triggers: string[];
  enabled: boolean;
}

const BUNDLES: SkillBundle[] = [
  {
    name: "core",
    description: "基础对话能力：文件操作、命令执行、搜索、记忆管理",
    maxTokens: 180,
    autoEnable: true,
    triggers: [],
    enabled: true,
  },
  {
    name: "flow",
    description: "工作效率工具：浏览器自动化、飞书集成、文档处理",
    maxTokens: 550,
    autoEnable: false,
    triggers: ["飞书", "browser", "网页", "文档", "PPT"],
    enabled: false,
  },
  {
    name: "development",
    description: "开发工具：代码审查、调试、Git 集成",
    maxTokens: 400,
    autoEnable: false,
    triggers: ["代码", "debug", "git", "test"],
    enabled: false,
  },
  {
    name: "creative",
    description: "创意工具：PPT、视频、图片、可视化",
    maxTokens: 600,
    autoEnable: false,
    triggers: ["PPT", "视频", "画图", "设计"],
    enabled: false,
  },
  {
    name: "research",
    description: "研究工具：深度调研、论文分析、数据对比",
    maxTokens: 450,
    autoEnable: false,
    triggers: ["论文", "分析", "调研", "对比"],
    enabled: false,
  },
];

export function SkillBundlesSettings() {
  const [bundles, setBundles] = useState<SkillBundle[]>(BUNDLES);
  const [maxContextTokens, setMaxContextTokens] = useState(2000);

  const toggleBundle = (name: string) => {
    if (name === "core") return; // Core 不可禁用
    
    setBundles(bundles.map(bundle => 
      bundle.name === name ? { ...bundle, enabled: !bundle.enabled } : bundle
    ));
  };

  const totalTokens = bundles
    .filter(b => b.enabled)
    .reduce((sum, b) => sum + b.maxTokens, 0);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>智能技能包</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground mb-4">
            根据使用场景自动加载合适的技能，减少 Context 占用，提升响应速度
          </p>

          <Tabs defaultValue="all" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="all">全部</TabsTrigger>
              <TabsTrigger value="enabled">已启用</TabsTrigger>
            </TabsList>

            <ScrollArea className="h-[400px] pr-4 mt-4">
              {bundles.map((bundle) => (
                <div
                  key={bundle.name}
                  className={`mb-4 p-4 rounded-lg border ${
                    bundle.enabled ? 'bg-primary/5 border-primary/20' : 'bg-transparent border-border'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <h4 className="font-semibold">{bundle.name}</h4>
                      <p className="text-sm text-muted-foreground">{bundle.description}</p>
                    </div>
                    {bundle.name !== "core" && (
                      <Switch
                        checked={bundle.enabled}
                        onCheckedChange={() => toggleBundle(bundle.name)}
                        disabled={bundle.autoEnable}
                      />
                    )}
                  </div>
                  
                  <div className="flex items-center gap-2 mt-2">
                    <Badge variant="secondary">~{bundle.maxTokens} tokens</Badge>
                    {bundle.triggers.length > 0 && (
                      <>
                        <span className="text-xs text-muted-foreground">触发:</span>
                        {bundle.triggers.slice(0, 3).map(trigger => (
                          <Badge key={trigger} variant="outline" className="ml-1">
                            {trigger}
                          </Badge>
                        ))}
                      </>
                    )}
                  </div>
                </div>
              ))}
            </ScrollArea>
          </Tabs>

          <div className="mt-6 pt-4 border-t">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-medium">最大 Context 限制</span>
              <span className="text-sm text-muted-foreground">{maxContextTokens} tokens</span>
            </div>
            <Slider
              value={[maxContextTokens]}
              min={500}
              max={5000}
              step={100}
              onValueChange={(v) => setMaxContextTokens(v[0])}
              className="mb-2"
            />
            <div className="text-xs text-muted-foreground">
              当前已用：{totalTokens} tokens ({Math.round((totalTokens / maxContextTokens) * 100)}%)
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
