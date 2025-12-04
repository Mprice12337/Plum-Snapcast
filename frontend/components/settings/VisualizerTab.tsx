import React from 'react';
import type {Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';

interface VisualizerTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

export const VisualizerTab: React.FC<VisualizerTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const handleIntegrationChange = (key: keyof SettingsType['integrations'], value: boolean) => {
    onSettingsChange({
      ...settings,
      integrations: {
        ...settings.integrations,
        [key]: value,
      },
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          Audio Visualizer
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Configure real-time audio visualization effects
        </p>
      </div>

      <div className="space-y-4">
        <Switch
          label="Enable Visualizer"
          checked={settings.integrations.visualizer}
          onChange={(val) => handleIntegrationChange('visualizer', val)}
          icon="fa-waveform-lines"
        />

        {settings.integrations.visualizer && (
          <div className="pl-8 space-y-6">
            <div className="p-4 bg-[var(--bg-tertiary)] rounded-lg border border-[var(--border-color)]">
              <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
                Coming Soon
              </h4>
              <p className="text-sm text-[var(--text-muted)]">
                Additional visualizer customization options will be available in a future update:
              </p>
              <ul className="mt-3 space-y-1 text-sm text-[var(--text-muted)] list-disc list-inside">
                <li>Visualizer style selection (bars, waveform, spectrum)</li>
                <li>Color customization</li>
                <li>Sensitivity and smoothing controls</li>
                <li>Position and size options</li>
              </ul>
            </div>

            <div>
              <p className="text-xs text-[var(--text-muted)] italic">
                The visualizer displays real-time audio waveforms synchronized with your music.
                It adapts to the current theme and accent color automatically.
              </p>
            </div>
          </div>
        )}
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          About the Visualizer
        </h4>
        <p className="text-xs text-[var(--text-muted)]">
          The audio visualizer analyzes the frequency spectrum of your music in real-time to create
          dynamic visual effects. It runs directly in your browser and has minimal impact on
          performance. Visualizer preferences are saved per-browser.
        </p>
      </div>
    </div>
  );
};
