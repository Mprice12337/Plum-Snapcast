import React from 'react';
import type {Stream} from '../types';

interface PlayerControlsProps {
    stream: Stream;
    volume: number;
    onVolumeChange: (volume: number) => void;
    onPlayPause: () => void;
    onSkip: (direction: 'next' | 'prev') => void;
}

const ControlButton: React.FC<{ onClick?: () => void; icon: string; size?: 'sm' | 'md' | 'lg' }> = ({
                                                                                                        onClick,
                                                                                                        icon,
                                                                                                        size = 'md'
                                                                                                    }) => {
    const sizeClasses = {
        sm: 'w-10 h-10 text-base',
        md: 'w-12 h-12 text-lg',
        lg: 'w-16 h-16 text-2xl',
    };
    return (
        <button
            onClick={onClick}
            className={`flex items-center justify-center rounded-full text-[var(--text-secondary)] bg-[var(--border-color)] hover:bg-[var(--bg-secondary-hover)] transition-colors duration-200 ${sizeClasses[size]}`}
            aria-label={icon.includes('play') ? 'Play' : icon.includes('pause') ? 'Pause' : icon.includes('backward') ? 'Previous track' : 'Next track'}
        >
            <i className={`fas ${icon}`}></i>
        </button>
    );
};

export const PlayerControls: React.FC<PlayerControlsProps> = ({
                                                                  stream,
                                                                  volume,
                                                                  onVolumeChange,
                                                                  onPlayPause,
                                                                  onSkip
                                                              }) => {
    const volumePercentage = volume;
    const sliderStyle = {
        background: `linear-gradient(to right, var(--accent-color) ${volumePercentage}%, var(--border-color) ${volumePercentage}%)`
    };

    return (
        <div className="flex flex-col md:flex-row items-center gap-6 px-4">
            {/* Mobile: Volume on top, Controls below */}
            {/* Desktop: Controls on left (centered under artwork), Volume on right */}

            {/* Volume Control - order-1 on mobile, order-2 on desktop */}
            <div className="flex items-center gap-3 w-full max-w-xs order-1 md:order-2 md:ml-auto">
                <i className="fas fa-volume-down text-[var(--text-secondary)] w-6 text-center" aria-hidden="true"></i>
                <input
                    type="range"
                    min="0"
                    max="100"
                    value={volume}
                    onChange={(e) => onVolumeChange(Number(e.target.value))}
                    className="w-full h-2 rounded-lg appearance-none cursor-pointer volume-slider"
                    style={sliderStyle}
                    aria-label="Volume control"
                />
                <i className="fas fa-volume-high text-[var(--text-secondary)] w-6 text-center" aria-hidden="true"></i>
            </div>

            {/* Media Controls - order-2 on mobile, order-1 on desktop */}
            <div className="flex items-center gap-4 order-2 md:order-1 md:ml-0 md:w-56 md:justify-center">
                <ControlButton icon="fa-backward-step" onClick={() => onSkip('prev')}/>
                <ControlButton icon={stream.isPlaying ? 'fa-pause' : 'fa-play'} onClick={onPlayPause} size="lg"/>
                <ControlButton icon="fa-forward-step" onClick={() => onSkip('next')}/>
            </div>
        </div>
    );
};