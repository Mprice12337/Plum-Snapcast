import React from 'react';
import type { Stream } from '../types';
import { formatTime } from '../utils/time';

interface NowPlayingProps {
  stream: Stream;
}

export const NowPlaying: React.FC<NowPlayingProps> = ({ stream }) => {
  const { currentTrack, progress } = stream;
  const progressPercent = (progress / currentTrack.duration) * 100;

  return (
    <div className="flex flex-col md:flex-row items-center gap-6 p-4">
      <div className="flex-shrink-0">
        <img
          src={currentTrack.albumArtUrl}
          alt={`Album art for ${currentTrack.album}`}
          className="w-48 h-48 md:w-56 md:h-56 rounded-lg shadow-lg object-cover transition-transform duration-300 hover:scale-105"
        />
      </div>
      <div className="flex-1 text-center md:text-left w-full">
        <h2 className="text-3xl font-bold truncate" title={currentTrack.title}>{currentTrack.title}</h2>
        <p className="text-lg text-[var(--text-secondary)] mt-1 truncate" title={currentTrack.artist}>{currentTrack.artist}</p>
        <p className="text-md text-[var(--text-muted)] mt-1 truncate" title={currentTrack.album}>{currentTrack.album}</p>
        
        <div className="mt-6 w-full">
          <div className="bg-[var(--border-color)] rounded-full h-2 w-full">
            <div
              className="bg-[var(--accent-color)] h-2 rounded-full transition-all duration-1000 ease-linear"
              style={{ width: `${progressPercent}%` }}
            ></div>
          </div>
          <div className="flex justify-between text-xs text-[var(--text-muted)] mt-2">
            <span>{formatTime(progress)}</span>
            <span>{formatTime(currentTrack.duration)}</span>
          </div>
        </div>
      </div>
    </div>
  );
};