import React from 'react';
import type {AccentColor, Settings as SettingsType, ThemeMode} from '../types';

interface SettingsProps {
    isOpen: boolean;
    onClose: () => void;
    settings: SettingsType;
    onSettingsChange: (settings: SettingsType) => void;
}

export const Settings: React.FC<SettingsProps> = ({isOpen, onClose, settings, onSettingsChange}) => {
    if (!isOpen) return null;

    const toggleIntegration = (key: keyof SettingsType['integrations']) => {
        onSettingsChange({
            ...settings,
            integrations: {
                ...settings.integrations,
                [key]: !settings.integrations[key]
            }
        });
    };

    const setThemeMode = (mode: ThemeMode) => {
        onSettingsChange({
            ...settings,
            theme: {...settings.theme, mode}
        });
    };

    const setAccent = (accent: AccentColor) => {
        onSettingsChange({
            ...settings,
            theme: {...settings.theme, accent}
        });
    };

    // Format integration names for display
    const formatIntegrationName = (key: string): string => {
        const nameMap: Record<string, string> = {
            airplay: 'AirPlay',
            spotifyConnect: 'Spotify Connect',
            bluetooth: 'Bluetooth',
            snapcast: 'Snapcast',
            visualizer: 'Visualizer'
        };
        return nameMap[key] || key;
    };

    return (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
             onClick={onClose}>
            <div className="bg-[var(--bg-secondary)] rounded-xl max-w-md w-full p-6 max-h-[80vh] overflow-y-auto"
                 onClick={(e) => e.stopPropagation()}>
                <div className="flex items-center justify-between mb-6">
                    <h2 className="text-2xl font-bold">Settings</h2>
                    <button
                        onClick={onClose}
                        className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                        aria-label="Close settings"
                    >
                        <i className="fas fa-times text-xl"></i>
                    </button>
                </div>

                {/* Integrations */}
                <div className="mb-6">
                    <h3 className="text-lg font-semibold mb-3 text-[var(--text-secondary)]">Audio Sources</h3>
                    <div className="space-y-2">
                        {Object.entries(settings.integrations).map(([key, value]) => (
                            <label
                                key={key}
                                className="flex items-center justify-between p-3 rounded-lg hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
                            >
                                <span className="font-medium">{formatIntegrationName(key)}</span>
                                <input
                                    type="checkbox"
                                    checked={value}
                                    onChange={() => toggleIntegration(key as keyof SettingsType['integrations'])}
                                    className="w-5 h-5 accent-[var(--accent-color)] cursor-pointer"
                                />
                            </label>
                        ))}
                    </div>
                </div>

                {/* Theme */}
                <div className="mb-6">
                    <h3 className="text-lg font-semibold mb-3 text-[var(--text-secondary)]">Theme</h3>
                    <div className="flex gap-2 mb-4">
                        {(['light', 'dark', 'system'] as ThemeMode[]).map(mode => (
                            <button
                                key={mode}
                                onClick={() => setThemeMode(mode)}
                                className={`flex-1 py-2 px-4 rounded-lg capitalize transition-colors ${
                                    settings.theme.mode === mode
                                        ? 'bg-[var(--accent-color)] text-white font-semibold'
                                        : 'bg-[var(--bg-tertiary)] hover:bg-[var(--bg-tertiary-hover)] text-[var(--text-primary)]'
                                }`}
                            >
                                {mode}
                            </button>
                        ))}
                    </div>
                </div>

                {/* Accent Color */}
                <div>
                    <h3 className="text-lg font-semibold mb-3 text-[var(--text-secondary)]">Accent Color</h3>
                    <div className="flex gap-3 justify-center">
                        {(['purple', 'blue', 'green', 'orange', 'red'] as AccentColor[]).map(color => {
                            const colorValues = {
                                purple: '#aa5cc3',
                                blue: '#3b82f6',
                                green: '#22c55e',
                                orange: '#f97316',
                                red: '#ef4444'
                            };

                            return (
                                <button
                                    key={color}
                                    onClick={() => setAccent(color)}
                                    className={`w-12 h-12 rounded-full transition-all ${
                                        settings.theme.accent === color
                                            ? 'ring-4 ring-offset-2 ring-offset-[var(--bg-secondary)] ring-[var(--accent-color)] scale-110'
                                            : 'hover:scale-105'
                                    }`}
                                    style={{
                                        backgroundColor: colorValues[color]
                                    }}
                                    aria-label={`${color} accent color`}
                                    title={color.charAt(0).toUpperCase() + color.slice(1)}
                                />
                            );
                        })}
                    </div>
                </div>
            </div>
        </div>
    );
};