import React from 'react';
import { Icon } from '../Icon';

export const AboutTab: React.FC = () => {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          About Plum-Snapcast
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Multi-room audio streaming with Snapcast
        </p>
      </div>

      <div className="space-y-6">
        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Version Information
          </h4>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Plum-Snapcast</span>
              <span className="text-[var(--text-primary)] font-mono">1.0.0</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-muted)]">Frontend</span>
              <span className="text-[var(--text-primary)] font-mono">React 19.1.1</span>
            </div>
          </div>
        </div>

        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Credits & Attribution
          </h4>
          <div className="space-y-3 text-sm text-[var(--text-muted)]">
            <div>
              <p className="font-semibold text-[var(--text-primary)] mb-1">Based on</p>
              <ul className="space-y-1 list-disc list-inside">
                <li>
                  <a
                    href="https://github.com/badaix/snapcast"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent-color)] hover:underline"
                  >
                    Snapcast
                  </a>
                  {' '}by Johannes Pohl
                </li>
                <li>
                  <a
                    href="https://github.com/firefrei/docker-snapcast"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent-color)] hover:underline"
                  >
                    docker-snapcast
                  </a>
                  {' '}by firefrei
                </li>
              </ul>
            </div>

            <div>
              <p className="font-semibold text-[var(--text-primary)] mb-1">Audio Sources</p>
              <ul className="space-y-1 list-disc list-inside">
                <li>
                  <a
                    href="https://github.com/mikebrady/shairport-sync"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent-color)] hover:underline"
                  >
                    Shairport-Sync
                  </a>
                  {' '}(AirPlay)
                </li>
                <li>
                  <a
                    href="https://github.com/Spotifyd/spotifyd"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent-color)] hover:underline"
                  >
                    Spotifyd
                  </a>
                  {' '}(Spotify Connect)
                </li>
                <li>
                  <a
                    href="https://github.com/hzeller/gmrender-resurrect"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-[var(--accent-color)] hover:underline"
                  >
                    gmrender-resurrect
                  </a>
                  {' '}(DLNA/UPnP)
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
          <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-3">
            Resources
          </h4>
          <div className="space-y-2 text-sm">
            <a
              href="https://github.com/your-username/Plum-Snapcast"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-[var(--accent-color)] hover:underline"
            >
              <Icon name="github" />
              <span>View on GitHub</span>
            </a>
            <a
              href="https://github.com/badaix/snapcast/blob/develop/doc/json_rpc_api/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-[var(--accent-color)] hover:underline"
            >
              <Icon name="book" />
              <span>Snapcast API Documentation</span>
            </a>
          </div>
        </div>

        <div className="text-center pt-4">
          <p className="text-xs text-[var(--text-muted)]">
            Built with Claude Code
          </p>
        </div>
      </div>
    </div>
  );
};
