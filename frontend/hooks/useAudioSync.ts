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

    useEffect(() => {
        // Clear any existing interval
        if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
        }

        if (stream?.isPlaying) {
            const serverProgress = stream.progress;

            // Compare server position to our PREDICTED position (not last server position)
            // This avoids false positives when backend sends periodic updates
            const predictedProgress = lastProgressRef.current;
            const positionJump = Math.abs(serverProgress - predictedProgress) > 2;

            if (positionJump || lastServerProgressRef.current === 0) {
                console.log(`[useAudioSync] Position sync: ${predictedProgress}s → ${serverProgress}s (jump: ${positionJump})`);
                lastProgressRef.current = serverProgress;
                lastServerProgressRef.current = serverProgress;
            }

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
    }, [stream?.isPlaying, stream?.id, stream?.progress, updateProgress]);
};
