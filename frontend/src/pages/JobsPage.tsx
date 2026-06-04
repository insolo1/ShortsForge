import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { jobs } from '../api/client';

export default function JobsPage() {
  const [url, setUrl] = useState('');
  const [shortLength, setShortLength] = useState(45);
  const [shortsCount, setShortsCount] = useState(5);

  const { data, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => jobs.list().then((r) => r.data.jobs),
    refetchInterval: 3000,
  });

  const uploadMutation = useMutation({
    mutationFn: () =>
      jobs.uploadUrl(url, shortLength, shortsCount),
    onSuccess: () => {
      setUrl('');
      refetch();
    },
  });

  const [selectedJob, setSelectedJob] = useState<string | null>(null);

  const { data: jobDetail } = useQuery({
    queryKey: ['job', selectedJob],
    queryFn: () => jobs.get(selectedJob!).then((r) => r.data),
    enabled: !!selectedJob,
    refetchInterval: 3000,
  });

  const { data: jobLogs } = useQuery({
    queryKey: ['jobLogs', selectedJob],
    queryFn: () => jobs.getLogs(selectedJob!).then((r) => r.data.logs),
    enabled: !!selectedJob,
    refetchInterval: 2000,
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">
          Jobs
        </h1>
        <Link to="/" className="text-purple-400 hover:text-purple-300">
          Dashboard
        </Link>
      </div>

      <div className="bg-gray-800 rounded-2xl p-6 mb-8">
        <h2 className="text-lg font-semibold mb-4">New Job from URL</h2>
        <div className="flex gap-3">
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="YouTube video URL..."
            className="flex-1 bg-gray-700 rounded-xl px-4 py-2 text-white placeholder-gray-500 border border-gray-600 focus:border-purple-500 outline-none"
          />
          <input
            type="number"
            value={shortLength}
            onChange={(e) => setShortLength(Number(e.target.value))}
            className="w-20 bg-gray-700 rounded-xl px-3 py-2 text-center text-white border border-gray-600 focus:border-purple-500 outline-none"
            title="Short length (s)"
          />
          <input
            type="number"
            value={shortsCount}
            onChange={(e) => setShortsCount(Number(e.target.value))}
            className="w-20 bg-gray-700 rounded-xl px-3 py-2 text-center text-white border border-gray-600 focus:border-purple-500 outline-none"
            title="Shorts count"
          />
          <button
            onClick={() => uploadMutation.mutate()}
            disabled={!url || uploadMutation.isPending}
            className="bg-purple-600 hover:bg-purple-700 disabled:bg-gray-600 px-6 py-2 rounded-xl font-medium transition"
          >
            {uploadMutation.isPending ? '...' : 'Start'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-800 rounded-2xl p-6">
          <h2 className="text-lg font-semibold mb-4">All Jobs</h2>
          <div className="space-y-2 max-h-96 overflow-y-auto">
            {(data || []).map((job: any) => (
              <div
                key={job.id}
                onClick={() => setSelectedJob(job.id)}
                className={`p-3 rounded-xl cursor-pointer transition flex items-center justify-between ${
                  selectedJob === job.id
                    ? 'bg-purple-600/20 border border-purple-500'
                    : 'bg-gray-700/50 hover:bg-gray-700'
                }`}
              >
                <div>
                  <div className="text-sm font-mono">{job.id.slice(0, 8)}...</div>
                  <div className="text-xs text-gray-400">{job.shorts_count} shorts</div>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-16 bg-gray-600 rounded-full h-1.5">
                    <div
                      className="bg-purple-500 h-1.5 rounded-full"
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>
                  <span className="text-xs text-gray-400">{job.progress}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {selectedJob && (
          <div className="bg-gray-800 rounded-2xl p-6">
            <h2 className="text-lg font-semibold mb-4">
              Job {selectedJob.slice(0, 8)}...
              <span
                className={`ml-2 text-xs px-2 py-0.5 rounded ${
                  jobDetail?.status === 'completed'
                    ? 'bg-green-500/20 text-green-400'
                    : jobDetail?.status === 'processing'
                      ? 'bg-blue-500/20 text-blue-400'
                      : 'bg-gray-500/20 text-gray-400'
                }`}
              >
                {jobDetail?.status}
              </span>
            </h2>
            <div className="w-full bg-gray-600 rounded-full h-2 mb-4">
              <div
                className="bg-purple-500 h-2 rounded-full transition-all"
                style={{ width: `${jobDetail?.progress || 0}%` }}
              />
            </div>
            <div className="max-h-80 overflow-y-auto space-y-1">
              {(jobLogs || []).map((log: any, i: number) => (
                <div
                  key={i}
                  className={`text-xs py-1 px-2 rounded ${
                    log.type === 'error'
                      ? 'bg-red-500/10 text-red-400'
                      : log.type === 'success'
                        ? 'bg-green-500/10 text-green-400'
                        : 'text-gray-400'
                  }`}
                >
                  {log.message}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
