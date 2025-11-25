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
            // Detect if server position changed significantly (seek/scrub detected)
            const serverProgress = stream.progress;
            const positionJump = Math.abs(serverProgress - lastServerProgressRef.current) > 2;

            // If position jumped OR this is a new stream/playback, reset to server position
            if (positionJump || lastServerProgressRef.current === 0) {
                console.log(`[useAudioSync] Position sync: ${lastServerProgressRef.current}s → ${serverProgress}s (jump: ${positionJump})`);
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
            // Reset when not playing
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
