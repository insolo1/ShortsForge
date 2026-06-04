import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import api from '../api/client';

export default function Dashboard() {
  const { data: jobsData } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.get('/jobs').then((r) => r.data.jobs),
    refetchInterval: 5000,
  });

  return (
    <div className="container mx-auto px-4 py-8">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold bg-gradient-to-r from-pink-500 to-purple-500 bg-clip-text text-transparent">
          Video to Shorts
        </h1>
        <div className="flex gap-4">
          <Link to="/jobs" className="text-purple-400 hover:text-purple-300">
            Jobs
          </Link>
          <button
            onClick={() => {
              document.cookie = 'token=; max-age=0';
              window.location.href = '/login';
            }}
            className="text-gray-400 hover:text-white"
          >
            Logout
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
        <div className="bg-gray-800 rounded-2xl p-6">
          <div className="text-3xl font-bold">{jobsData?.length || 0}</div>
          <div className="text-gray-400 text-sm">Total jobs</div>
        </div>
        <div className="bg-gray-800 rounded-2xl p-6">
          <div className="text-3xl font-bold">
            {jobsData?.filter((j: any) => j.status === 'completed').length || 0}
          </div>
          <div className="text-gray-400 text-sm">Completed</div>
        </div>
        <div className="bg-gray-800 rounded-2xl p-6">
          <div className="text-3xl font-bold">
            {jobsData?.filter((j: any) => j.status === 'processing').length || 0}
          </div>
          <div className="text-gray-400 text-sm">Processing</div>
        </div>
      </div>

      <div className="bg-gray-800 rounded-2xl p-6">
        <h2 className="text-xl font-semibold mb-4">Recent Jobs</h2>
        <div className="space-y-2">
          {jobsData?.slice(0, 10).map((job: any) => (
            <div
              key={job.id}
              className="flex items-center justify-between p-3 bg-gray-700/50 rounded-xl"
            >
              <div className="truncate flex-1">
                <span className="text-sm font-mono">{job.id.slice(0, 8)}...</span>
                <span className="text-gray-400 text-sm ml-2">
                  {job.shorts_count} shorts
                </span>
              </div>
              <div className="flex items-center gap-3">
                <div className="w-24 bg-gray-600 rounded-full h-2">
                  <div
                    className="bg-purple-500 h-2 rounded-full transition-all"
                    style={{ width: `${job.progress}%` }}
                  />
                </div>
                <span
                  className={`text-xs px-2 py-1 rounded ${
                    job.status === 'completed'
                      ? 'bg-green-500/20 text-green-400'
                      : job.status === 'processing'
                        ? 'bg-blue-500/20 text-blue-400'
                        : 'bg-gray-500/20 text-gray-400'
                  }`}
                >
                  {job.status}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
