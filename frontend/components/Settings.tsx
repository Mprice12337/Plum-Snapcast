import React, {useState} from 'react';
import type {Settings as SettingsType} from '../types';
import {TabBar, type Tab} from './TabBar';
import {IntegrationsTab} from './settings/IntegrationsTab';
import {SnapcastTab} from './settings/SnapcastTab';
import {ThemeTab} from './settings/ThemeTab';
import {VisualizerTab} from './settings/VisualizerTab';
import {AboutTab} from './settings/AboutTab';

interface SettingsProps {
    settings: SettingsType;
    onSettingsChange: (newSettings: SettingsType) => void;
    onClose: () => void;
}

const tabs: Tab[] = [
    {id: 'integrations', label: 'Integrations', icon: 'fa-puzzle-piece'},
    {id: 'snapcast', label: 'Snapcast', icon: 'fa-network-wired'},
    {id: 'theme', label: 'Theme', icon: 'fa-palette'},
    {id: 'visualizer', label: 'Visualizer', icon: 'fa-waveform-lines'},
    {id: 'about', label: 'About', icon: 'fa-info-circle'},
];

export const Settings: React.FC<SettingsProps> = ({settings, onSettingsChange, onClose}) => {
    const [activeTab, setActiveTab] = useState('integrations');

    const renderTabContent = () => {
        switch (activeTab) {
            case 'integrations':
                return <IntegrationsTab settings={settings} onSettingsChange={onSettingsChange} />;
            case 'snapcast':
                return <SnapcastTab settings={settings} onSettingsChange={onSettingsChange} />;
            case 'theme':
                return <ThemeTab settings={settings} onSettingsChange={onSettingsChange} />;
            case 'visualizer':
                return <VisualizerTab settings={settings} onSettingsChange={onSettingsChange} />;
            case 'about':
                return <AboutTab />;
            default:
                return null;
        }
    };

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
            onClick={onClose}
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
        >
            <div
                className="relative w-full max-w-2xl m-4 bg-[var(--bg-secondary)] rounded-2xl shadow-2xl border border-[var(--border-color)] flex flex-col max-h-[85vh]"
                onClick={e => e.stopPropagation()}
            >
                <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border-color)]">
                    <h2 id="settings-title" className="text-2xl font-bold text-[var(--text-primary)]">Settings</h2>
                    <button
                        onClick={onClose}
                        className="w-8 h-8 flex items-center justify-center rounded-full text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]"
                        aria-label="Close settings"
                    >
                        <i className="fas fa-times"></i>
                    </button>
                </div>

                <TabBar tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />

                <div className="p-6 overflow-y-auto flex-1">
                    {renderTabContent()}
                </div>
            </div>
        </div>
    );
};