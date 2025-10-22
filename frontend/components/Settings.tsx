import React from 'react';
import type {AccentColor, Settings as SettingsType, ThemeMode} from '../types';
import {Switch} from './Switch';

interface SettingsProps {
    settings: SettingsType;
    onSettingsChange: (newSettings: SettingsType) => void;
    onClose: () => void;
}

const themeModes: { value: ThemeMode; label: string; icon: string }[] = [
    {value: 'light', label: 'Light', icon: 'fa-sun'},
    {value: 'dark', label: 'Dark', icon: 'fa-moon'},
    {value: 'system', label: 'System', icon: 'fa-desktop'},
];

const accentColors: { name: AccentColor, className: string }[] = [
    {name: 'purple', className: 'bg-[#aa5cc3]'},
    {name: 'blue', className: 'bg-[#3b82f6]'},
    {name: 'green', className: 'bg-[#22c55e]'},
    {name: 'orange', className: 'bg-[#f97316]'},
    {name: 'red', className: 'bg-[#ef4444]'},
];

const Section: React.FC<React.PropsWithChildren<{ title: string }>> = ({title, children}) => (
    <div>
        <h3 className="text-sm font-semibold uppercase text-[var(--text-muted)] tracking-wider mb-4">{title}</h3>
        <div className="space-y-4">{children}</div>
    </div>
);

export const Settings: React.FC<SettingsProps> = ({settings, onSettingsChange, onClose}) => {

    const handleIntegrationChange = (key: keyof SettingsType['integrations'], value: boolean) => {
        onSettingsChange({
            ...settings,
            integrations: {
                ...settings.integrations,
                [key]: value,
            }
        });
    };

    const handleThemeModeChange = (mode: ThemeMode) => {
        onSettingsChange({
            ...settings,
            theme: {
                ...settings.theme,
                mode,
            }
        });
    }

    const handleAccentChange = (accent: AccentColor) => {
        onSettingsChange({
            ...settings,
            theme: {
                ...settings.theme,
                accent,
            }
        });
    }

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
        >
            <div
                className="relative w-full max-w-lg m-4 bg-[var(--bg-secondary)] rounded-2xl shadow-2xl border border-[var(--border-color)]"
                onClick={e => e.stopPropagation()}
            >
                <div className="flex items-center justify-between p-6 border-b border-[var(--border-color)]">
                    <h2 id="settings-title" className="text-2xl font-bold text-[var(--text-primary)]">Settings</h2>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 flex items-center justify-center rounded-full text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
                        aria-label="Close settings"
                    >
                        <i className="fas fa-times"></i>
                    </button>
                </div>
                <div className="p-6 space-y-8 max-h-[70vh] overflow-y-auto">
                    <Section title="Integrations">
                        <Switch label="AirPlay Enabled" checked={settings.integrations.airplay}
                                onChange={(val) => handleIntegrationChange('airplay', val)}/>
                        <Switch label="Spotify Connect Enabled" checked={settings.integrations.spotifyConnect}
                                onChange={(val) => handleIntegrationChange('spotifyConnect', val)}/>
                        <Switch label="Snapcast Stream Enabled" checked={settings.integrations.snapcast}
                                onChange={(val) => handleIntegrationChange('snapcast', val)}/>
                    </Section>

                    <Section title="Appearance">
                        <Switch label="Visualizer Enabled" checked={settings.integrations.visualizer}
                                onChange={(val) => handleIntegrationChange('visualizer', val)}/>
                        <div>
                            <h4 className="text-base text-[var(--text-secondary)] mb-3">Theme</h4>
                            <div className="grid grid-cols-3 gap-2 p-1 rounded-lg bg-[var(--bg-tertiary)]">
                                {themeModes.map(mode => (
                                    <button key={mode.value} onClick={() => handleThemeModeChange(mode.value)}
                                            className={`px-3 py-2 text-sm font-semibold rounded-md flex items-center justify-center gap-2 transition-colors ${settings.theme.mode === mode.value ? 'bg-[var(--accent-color)] text-white' : 'text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary-hover)]'}`}
                                    >
                                        <i className={`fas ${mode.icon}`}></i>
                                        {mode.label}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div>
                            <h4 className="text-base text-[var(--text-secondary)] mb-3">Accent Color</h4>
                            <div className="flex items-center gap-4">
                                {accentColors.map(color => (
                                    <button key={color.name} onClick={() => handleAccentChange(color.name)}
                                            className={`w-8 h-8 rounded-full ${color.className} transition-transform hover:scale-110 ${settings.theme.accent === color.name ? 'ring-2 ring-offset-2 ring-offset-[var(--bg-secondary)] ring-[var(--accent-color)]' : ''}`}
                                            aria-label={`Set accent color to ${color.name}`}
                                    />
                                ))}
                            </div>
                        </div>
                    </Section>
                </div>
            </div>
        </div>
    );
};