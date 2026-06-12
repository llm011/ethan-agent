import { useEffect, useState, useCallback } from "react";
import { ScheduleJob, fetchSchedules, deleteSchedule, patchSchedule } from "@/lib/api";
import { RefreshCw, Play, Pause, Trash2, Clock } from "lucide-react";

export function ScheduleView() {
  const [jobs, setJobs] = useState<ScheduleJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSchedules = useCallback(() => {
    let mounted = true;
    fetchSchedules()
      .then(data => {
        if (mounted) {
          setJobs(data);
          setLoading(false);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          const error = err as Error;
          setError(error.message || "Failed to load schedules");
          setLoading(false);
        }
      });
    return () => { mounted = false; };
  }, []);

  useEffect(() => {
    const cleanup = loadSchedules();
    return cleanup;
  }, [loadSchedules]);

  const handleToggleState = async (job: ScheduleJob) => {
    try {
      setLoading(true);
      // Assuming missing state implies active if it has a next_run_time
      const isCurrentlyActive = job.state === "active" || (job.state == null && job.next_run_time !== null);
      const newState = isCurrentlyActive ? "paused" : "active";
      await patchSchedule(job.id, newState);
      loadSchedules();
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Failed to toggle job: ${error.message}`);
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("Are you sure you want to delete this schedule?")) return;
    try {
      setLoading(true);
      await deleteSchedule(id);
      loadSchedules();
    } catch (err: unknown) {
      const error = err as Error;
      setError(`Failed to delete job: ${error.message}`);
      setLoading(false);
    }
  };

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return "Never";
    return new Date(dateStr).toLocaleString();
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-white dark:bg-zinc-900 overflow-hidden">
      <div className="h-14 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between px-4 shrink-0">
        <div className="flex items-center gap-2">
          <Clock className="w-5 h-5 text-zinc-500" />
          <h1 className="font-medium text-zinc-900 dark:text-zinc-100">Schedules</h1>
        </div>
        <button
          onClick={() => {
            setLoading(true);
            loadSchedules();
          }}
          className="p-2 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-md transition-colors"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4 md:p-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-md text-sm">
            {error}
          </div>
        )}

        {loading && jobs.length === 0 ? (
          <div className="flex items-center justify-center h-40 text-zinc-500">
            Loading schedules...
          </div>
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-zinc-500 space-y-2">
            <Clock className="w-8 h-8 opacity-20" />
            <p>No schedules found.</p>
            <p className="text-sm opacity-70">Create one by asking the assistant in Chat.</p>
          </div>
        ) : (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg overflow-hidden">
            <table className="w-full text-sm text-left">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
                <tr>
                  <th className="px-4 py-3 font-medium">Name</th>
                  <th className="px-4 py-3 font-medium">Trigger</th>
                  <th className="px-4 py-3 font-medium">Next Run Time</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 text-zinc-900 dark:text-zinc-100">
                {jobs.map((job) => {
                  const isActive = job.state === "active" || (job.state == null && job.next_run_time !== null);

                  return (
                    <tr key={job.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
                      <td className="px-4 py-3 font-medium">{job.name}</td>
                      <td className="px-4 py-3 font-mono text-xs">{job.trigger}</td>
                      <td className="px-4 py-3">{formatDate(job.next_run_time)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          isActive
                            ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                            : "bg-zinc-100 text-zinc-800 dark:bg-zinc-800 dark:text-zinc-400"
                        }`}>
                          {isActive ? "Active" : "Paused"}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleToggleState(job)}
                            className="p-1.5 text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded transition-colors"
                            title={isActive ? "暂停 (Pause)" : "恢复 (Resume)"}
                          >
                            {isActive ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
                          </button>
                          <button
                            onClick={() => handleDelete(job.id)}
                            className="p-1.5 text-zinc-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                            title="删除 (Delete)"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}