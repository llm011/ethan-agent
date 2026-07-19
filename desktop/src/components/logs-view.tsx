import React, { useState, useEffect, useRef } from "react";
import { fetchLogs } from "@/lib/api";
import { RefreshCw, Search, Terminal } from "lucide-react";

export function LogsView() {
  const [logType, setLogType] = useState<"backend" | "frontend">("backend");
  const [logs, setLogs] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);
  const [query, setQuery] = useState<string>("");
  const [searchInput, setSearchInput] = useState<string>("");
  const [lines, setLines] = useState<number>(500);
  const scrollRef = useRef<HTMLPreElement>(null);

  const loadLogs = async () => {
    setLoading(true);
    try {
      const data = await fetchLogs(logType, lines, query);
      setLogs(data);
    } catch (err) {
      console.error("Error loading logs", err);
      setLogs("Error loading logs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLogs();
  }, [logType, query, lines]);

  useEffect(() => {
    // Auto-scroll to bottom when logs change
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setQuery(searchInput);
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 text-slate-300 font-mono text-sm">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-slate-700 bg-slate-800">
        <div className="flex items-center gap-4">
          <Terminal className="w-5 h-5 text-indigo-400" />
          <h2 className="text-lg font-semibold text-white">Logs</h2>
          <div className="flex bg-slate-900 rounded-lg p-1 border border-slate-700 ml-4">
            <button
              onClick={() => setLogType("backend")}
              className={`px-3 py-1 rounded-md text-sm transition-colors ${
                logType === "backend" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"
              }`}
            >
              Backend
            </button>
            <button
              onClick={() => setLogType("frontend")}
              className={`px-3 py-1 rounded-md text-sm transition-colors ${
                logType === "frontend" ? "bg-indigo-600 text-white" : "text-slate-400 hover:text-white"
              }`}
            >
              Frontend
            </button>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <form onSubmit={handleSearch} className="relative flex items-center">
            <Search className="w-4 h-4 absolute left-2 text-slate-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Filter logs..."
              className="pl-8 pr-3 py-1 bg-slate-900 border border-slate-700 rounded-md text-sm focus:outline-none focus:border-indigo-500 text-white"
            />
          </form>
          
          <select 
            value={lines}
            onChange={(e) => setLines(Number(e.target.value))}
            className="bg-slate-900 border border-slate-700 text-white py-1 px-2 rounded-md text-sm"
          >
            <option value={100}>100 lines</option>
            <option value={500}>500 lines</option>
            <option value={1000}>1000 lines</option>
            <option value={0}>All (Warning)</option>
          </select>

          <button
            onClick={loadLogs}
            disabled={loading}
            className="p-1.5 rounded-md hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            title="Refresh logs"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Log Content */}
      <div className="flex-1 overflow-hidden p-4">
        {loading && !logs ? (
          <div className="h-full flex items-center justify-center text-slate-500">
            Loading logs...
          </div>
        ) : (
          <pre 
            ref={scrollRef}
            className="h-full overflow-y-auto whitespace-pre-wrap break-all p-4 bg-slate-950 rounded-lg border border-slate-800 text-green-400 leading-relaxed shadow-inner"
          >
            {logs || (loading ? "Loading..." : "No logs found.")}
          </pre>
        )}
      </div>
    </div>
  );
}
