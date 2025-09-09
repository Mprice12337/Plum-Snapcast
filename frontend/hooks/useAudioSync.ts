
import { useEffect, useRef } from 'react';
import type { Stream } from '../types';

export const useAudioSync = (
  stream: Stream | undefined,
  updateProgress: (streamId: string, newProgress: number) => void
) => {
  const intervalRef = useRef<number | null>(null);

  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }

    if (stream?.isPlaying) {
      intervalRef.current = window.setInterval(() => {
        updateProgress(stream.id, stream.progress + 1);
      }, 1000);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [stream?.isPlaying, stream?.id, stream?.progress, updateProgress]);
};
