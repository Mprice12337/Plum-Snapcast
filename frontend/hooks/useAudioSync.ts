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

            // Calculate drift: how far off is server from our prediction?
            const drift = Math.abs(serverProgress - predictedProgress);

            // Only sync on LARGE jumps (seeks) or initial connection
            // Ignore small drifts from periodic backend updates (≤3s)
            const isInitialConnection = lastServerProgressRef.current === 0;
            const isUserSeek = drift > 5;  // Only sync on 5+ second jumps

            if (isUserSeek || isInitialConnection) {
                console.log(`[useAudioSync] Position sync: ${predictedProgress}s → ${serverProgress}s (drift: ${drift}s, seek: ${isUserSeek}, initial: ${isInitialConnection})`);
                lastProgressRef.current = serverProgress;
                lastServerProgressRef.current = serverProgress;
                // Update UI immediately to prevent snap-back
                if (stream?.id) {
                    updateProgress(stream.id, serverProgress);
                }
            } else if (drift > 2) {
                // Log ignored updates for debugging
                console.log(`[useAudioSync] Ignoring small drift: ${drift}s (server: ${serverProgress}s, predicted: ${predictedProgress}s)`);
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
