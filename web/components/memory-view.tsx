"use client";

import { useEffect, useState } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";


import { Fact, Episode, fetchFacts, fetchEpisodes } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { Loader2, RefreshCw, ArrowLeft } from "lucide-react";
import { Badge } from "@/components/ui/badge";


const CJK = /[一-鿿㐀-䶿　-〿＀-￯⺀-⻿]/;
function fixBold(text: string): string {
  let fixed = text.replace(/\*\*\s+([^\*]+?)\s+\*\*/g, '**$1**');
  fixed = fixed
    .replace(/([^\s*_\\`])\*\*/g, (match, c) => (CJK.test(c) ? `${c}​**` : `${c} **`))
    .replace(/\*\*([^\s*_\\`])/g, (match, c) => (CJK.test(c) ? `**​${c}` : `** ${c}`));
  return fixed;
}

const markdownComponents = {
  pre: ({ children }: any) => <pre className="bg-background/50 rounded-lg p-3 overflow-x-auto text-xs">{children}</pre>,
  code: ({ className, children, ...props }: any) => {
    const isInline = !className;
    return isInline
      ? <code className="bg-background/50 px-1 py-0.5 rounded text-xs" {...props}>{children}</code>
      : <code className={className} {...props}>{children}</code>;
  },
};

export function MemoryView() {
  const [activeTab, setActiveTab] = useState<"facts" | "episodes">("facts");
  const [facts, setFacts] = useState<Fact[]>([]);
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(false);

  const [selectedFact, setSelectedFact] = useState<Fact | null>(null);
  const [selectedEpisode, setSelectedEpisode] = useState<Episode | null>(null);


  const loadData = async () => {
    setLoading(true);
    try {
      if (activeTab === "facts") {
        const data = await fetchFacts();
        setFacts(data);
      } else {
        const data = await fetchEpisodes();
        setEpisodes(data);
      }
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [activeTab]);

  return (
    <div className="flex flex-col h-full bg-background text-foreground">
      <header className="h-12 border-b border-border flex items-center px-4 justify-between shrink-0">
        <div className="flex gap-4">
          <button
            className={`text-sm font-medium transition-colors hover:text-primary ${activeTab === "facts" ? "text-primary" : "text-muted-foreground"}`}
            onClick={() => setActiveTab("facts")}
          >
            长期记忆 (Facts)
          </button>
          <button
            className={`text-sm font-medium transition-colors hover:text-primary ${activeTab === "episodes" ? "text-primary" : "text-muted-foreground"}`}
            onClick={() => setActiveTab("episodes")}
          >
            历史片段 (Episodes)
          </button>
        </div>
        <Button variant="ghost" size="icon" onClick={loadData} disabled={loading}>
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
        </Button>
      </header>

      
      {selectedFact ? (
        <div className="flex-1 flex flex-col p-6 max-w-4xl mx-auto w-full">
          <Button variant="ghost" className="w-fit mb-6 text-muted-foreground" onClick={() => setSelectedFact(null)}>
            <ArrowLeft className="h-4 w-4 mr-2" /> 返回记忆列表
          </Button>
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-bold">记忆详情 (Fact) - {selectedFact.category}</h2>
            <Badge variant={selectedFact.confidence > 0.8 ? "default" : "secondary"}>
              置信度: {Math.round(selectedFact.confidence * 100)}%
            </Badge>
          </div>
          <div className="prose prose-base dark:prose-invert max-w-none bg-muted/20 p-6 rounded-xl border border-border">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {fixBold(selectedFact.content || "*Empty*")}
            </ReactMarkdown>
          </div>
          <div className="flex flex-col gap-2 mt-8 text-sm text-muted-foreground bg-muted/10 p-4 rounded-lg">
            <span><strong>来源 (Source):</strong> {selectedFact.source || "未知"}</span>
            <span><strong>更新时间:</strong> {selectedFact.created_at ? new Date(selectedFact.created_at * 1000).toLocaleString() : "未知"}</span>
          </div>
        </div>
      ) : selectedEpisode ? (
        <div className="flex-1 flex flex-col p-6 max-w-4xl mx-auto w-full">
          <Button variant="ghost" className="w-fit mb-6 text-muted-foreground" onClick={() => setSelectedEpisode(null)}>
            <ArrowLeft className="h-4 w-4 mr-2" /> 返回历史片段
          </Button>
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-2xl font-bold">会话片段 (Episode)</h2>
            <span className="text-sm text-muted-foreground">{new Date(selectedEpisode.timestamp * 1000).toLocaleString()}</span>
          </div>
          <div className="flex gap-2 mb-6 flex-wrap">
            {selectedEpisode.keywords?.map((kw, i) => (
              <span key={i} className="px-3 py-1 bg-primary/10 text-primary rounded-full text-sm font-medium">
                {kw}
              </span>
            ))}
          </div>
          <div className="prose prose-base dark:prose-invert max-w-none bg-muted/20 p-6 rounded-xl border border-border">
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {fixBold(selectedEpisode.summary || "*Empty*")}
            </ReactMarkdown>
          </div>
          <div className="flex flex-col gap-2 mt-8 text-sm text-muted-foreground bg-muted/10 p-4 rounded-lg">
            <span><strong>Session ID:</strong> {selectedEpisode.session_id}</span>
            <span><strong>模型 (Model):</strong> {selectedEpisode.model}</span>
            <span><strong>对话轮数:</strong> {selectedEpisode.turn_count} turns</span>
          </div>
        </div>
      ) : (
        <ScrollArea className="flex-1">
        <div className="p-4 pb-6">

        {activeTab === "facts" && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {facts.map((fact, i) => (
              <Card key={i} className="cursor-pointer hover:border-primary hover:shadow-md hover:bg-muted/20 transition-all shadow-none border-border/60 bg-muted/10" onClick={() => setSelectedFact(fact)}>
                <CardHeader className="pb-2">
                  <div className="flex justify-between items-start">
                    <CardTitle className="text-sm font-semibold">{fact.category}</CardTitle>
                    <Badge variant={fact.confidence > 0.8 ? "default" : "secondary"}>
                      {Math.round(fact.confidence * 100)}%
                    </Badge>
                  </div>
                  <CardDescription className="text-xs">
                    {new Date(fact.created_at * 1000).toLocaleString()}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm whitespace-pre-wrap">{fact.content}</p>
                </CardContent>
              </Card>
            ))}
            {facts.length === 0 && !loading && (
              <div className="col-span-full text-center text-muted-foreground py-8">
                暂无长期记忆
              </div>
            )}
          </div>
        )}

        {activeTab === "episodes" && (
          <div className="space-y-4">
            {episodes.map((episode, i) => (
              <Card key={i} className="cursor-pointer hover:border-primary hover:shadow-md hover:bg-muted/20 transition-all shadow-none border-border/60 bg-muted/10" onClick={() => setSelectedEpisode(episode)}>
                <CardHeader className="pb-2">
                  <div className="flex justify-between items-center">
                    <CardTitle className="text-sm font-semibold">
                      {new Date(episode.timestamp * 1000).toLocaleString()}
                    </CardTitle>
                    <span className="text-xs text-muted-foreground">{episode.turn_count} turns</span>
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-sm mb-3">{episode.summary}</p>
                  <div className="flex flex-wrap gap-1">
                    {episode.keywords.map((kw, i) => (
                      <Badge key={i} variant="outline" className="text-[10px]">
                        {kw}
                      </Badge>
                    ))}
                  </div>
                </CardContent>
              </Card>
            ))}
            {episodes.length === 0 && !loading && (
              <div className="text-center text-muted-foreground py-8">
                暂无历史片段
              </div>
            )}
          </div>
        )}

        </div>
        </ScrollArea>
      )}
    </div>
  );
}

