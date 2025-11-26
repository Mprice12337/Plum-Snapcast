import {useEffect, useRef} from 'react';
import type {Stream} from '../types';

/**
 * Audio sync hook for client-side progress tracking.
 *
 * This provides smooth second-by-second progress updates between server position updates.
 * For sources that provide server position (Spotify, Plexamp), this interpolates between
 * server updates. For sources without server position (AirPlay, Bluetooth, DLNA), this
 * provides the only progress tracking via client-side estimation.
 */
export const useAudioSync = (
    stream: Stream | undefined,
    updateProgress: (streamId: string, newProgress: number) => void
) => {
    const intervalRef = useRef<number | null>(null);
    const lastProgressRef = useRef<number>(0);
    const lastServerProgressRef = useRef<number>(0);

    // Separate effect to monitor position changes WITHOUT restarting interval
    useEffect(() => {
        if (stream?.isPlaying && stream?.progress !== undefined) {
            const serverProgress = stream.progress;
            const predictedProgress = lastProgressRef.current;
            const positionJump = Math.abs(serverProgress - predictedProgress) > 2;

            // Only sync if there's a significant jump or this is the first update
            if (positionJump || lastServerProgressRef.current === 0) {
                console.log(`[useAudioSync] Position sync: ${predictedProgress}s → ${serverProgress}s (jump: ${positionJump})`);
                lastProgressRef.current = serverProgress;
                lastServerProgressRef.current = serverProgress;
                // Update UI immediately to prevent snap-back
                if (stream?.id) {
                    updateProgress(stream.id, serverProgress);
                }
            }
        }
    }, [stream?.progress, stream?.isPlaying, stream?.id, updateProgress]);

    // Main effect to start/stop the interval based on playback state
    useEffect(() => {
        // Clear any existing interval
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }

        if (stream?.isPlaying) {
            // Start interval to increment progress every second
            intervalRef.current = window.setInterval(() => {
                // Increment from last known progress
                const newProgress = lastProgressRef.current + 1;
                lastProgressRef.current = newProgress;
                updateProgress(stream.id, newProgress);
            }, 1000);
        } else {
            lastServerProgressRef.current = 0;
        }

        return () => {
            if (intervalRef.current) {
                clearInterval(intervalRef.current);
            }
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [stream?.isPlaying, stream?.id, updateProgress]);
};
