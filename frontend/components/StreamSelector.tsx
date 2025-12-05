import React, {useEffect, useRef, useState} from 'react';
import type {Stream} from '../types';
import { Icon } from './Icon';

interface StreamSelectorProps {
    streams: Stream[];
    currentStreamId: string | null;
    onSelectStream: (streamId: string | null) => void;
    federationEnabled?: boolean;
}

export const StreamSelector: React.FC<StreamSelectorProps> = ({streams, currentStreamId, onSelectStream, federationEnabled = false}) => {
    const [isOpen, setIsOpen] = useState(false);
    const wrapperRef = useRef<HTMLDivElement>(null);
    const currentStream = streams.find(s => s.id === currentStreamId);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [wrapperRef]);

    const handleSelect = (streamId: string | null) => {
        onSelectStream(streamId);
        setIsOpen(false);
    };

    const groupedStreams = React.useMemo(() => {
        if (!federationEnabled) {
            return { ungrouped: streams };
        }

        const groups: { [serverName: string]: Stream[] } = {};
        streams.forEach(stream => {
            const serverName = stream.serverName || 'Unknown Server';
            if (!groups[serverName]) {
                groups[serverName] = [];
            }
            groups[serverName].push(stream);
        });
        return groups;
    }, [streams, federationEnabled]);

    return (
        <div ref={wrapperRef} className="relative">
            <button
                onClick={() => setIsOpen(!isOpen)}
                className="w-full flex justify-between items-center text-left p-1 -m-1"
                aria-haspopup="listbox"
                aria-expanded={isOpen}
                aria-label="Select audio stream source"
            >
        <span className="text-3xl font-bold text-[var(--accent-color)] truncate pr-4">
          {currentStream ? currentStream.name : 'Select a Source'}
        </span>
                <Icon name="chevron-down" className={`text-[var(--text-secondary)] transition-transform duration-200 ${isOpen ? 'rotate-180' : ''}`} aria-hidden />
            </button>

            {isOpen && (
                <div
                    className="absolute z-10 top-full mt-2 w-full max-w-xs bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-xl"
                    role="listbox"
                >
                    <ul className="py-2 text-base text-[var(--text-primary)] max-h-60 overflow-auto">
                        <li role="option" aria-selected={!currentStreamId}>
                            <button
                                onClick={() => handleSelect(null)}
                                className="block w-full text-left px-4 py-2 text-[var(--text-secondary)] hover:bg-[var(--bg-secondary-hover)]"
                            >
                                None
                            </button>
                        </li>
                        {federationEnabled ? (
                            Object.entries(groupedStreams).map(([serverName, serverStreams]) => (
                                <React.Fragment key={serverName}>
                                    <li className="px-4 py-2 text-xs font-semibold text-[var(--text-secondary)] uppercase tracking-wider border-t border-[var(--border-color)] mt-2 first:mt-0 first:border-0">
                                        {serverName}
                                    </li>
                                    {serverStreams.map(s => (
                                        <li key={s.id} role="option" aria-selected={currentStreamId === s.id}>
                                            <button
                                                onClick={() => handleSelect(s.id)}
                                                className={`block w-full text-left px-4 py-2 hover:bg-[var(--bg-secondary-hover)] transition-colors ${currentStreamId === s.id ? 'font-semibold text-[var(--accent-color)]' : ''}`}
                                            >
                                                {s.name}
                                            </button>
                                        </li>
                                    ))}
                                </React.Fragment>
                            ))
                        ) : (
                            streams.map(s => (
                                <li key={s.id} role="option" aria-selected={currentStreamId === s.id}>
                                    <button
                                        onClick={() => handleSelect(s.id)}
                                        className={`block w-full text-left px-4 py-2 hover:bg-[var(--bg-secondary-hover)] transition-colors ${currentStreamId === s.id ? 'font-semibold text-[var(--accent-color)]' : ''}`}
                                    >
                                        {s.name}
                                    </button>
                                </li>
                            ))
                        )}
                    </ul>
                </div>
            )}
        </div>
    );
};