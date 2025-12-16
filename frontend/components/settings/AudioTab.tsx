import React, {useState, useEffect} from 'react';
import type {Settings as SettingsType} from '../../types';
import {audioService, type AudioDevice, type ConfiguredInputDevice, DeviceType} from '../../services/audioService';
import {Icon} from '../Icon';

interface AudioTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

type LoadingState = 'idle' | 'loading' | 'success' | 'error';

export const AudioTab: React.FC<AudioTabProps> = ({settings, onSettingsChange}) => {
  const [outputDevices, setOutputDevices] = useState<AudioDevice[]>([]);
  const [currentDevice, setCurrentDevice] = useState<string>('');
  const [selectedDevice, setSelectedDevice] = useState<string>('');
  const [loadingState, setLoadingState] = useState<LoadingState>('idle');
  const [applyingState, setApplyingState] = useState<LoadingState>('idle');
  const [errorMessage, setErrorMessage] = useState<string>('');
  const [successMessage, setSuccessMessage] = useState<string>('');

  // Input devices state
  const [availableInputDevices, setAvailableInputDevices] = useState<AudioDevice[]>([]);
  const [configuredInputDevices, setConfiguredInputDevices] = useState<ConfiguredInputDevice[]>([]);
  const [inputLoadingState, setInputLoadingState] = useState<LoadingState>('idle');
  const [expandedInputDevice, setExpandedInputDevice] = useState<string | null>(null);
  const [editingNames, setEditingNames] = useState<Record<string, string>>({});

  // Load output devices on mount
  useEffect(() => {
    loadDevices();
    loadInputDevices();
  }, []);

  const loadDevices = async () => {
    setLoadingState('loading');
    setErrorMessage('');

    try {
      // Load available devices
      const devices = await audioService.getOutputDevices();
      setOutputDevices(devices);

      // Load current device
      const current = await audioService.getCurrentOutputDevice();
      setCurrentDevice(current.hw_id);
      setSelectedDevice(current.hw_id);

      setLoadingState('success');
    } catch (error) {
      console.error('Failed to load audio devices:', error);
      setErrorMessage(error instanceof Error ? error.message : 'Failed to load audio devices');
      setLoadingState('error');
    }
  };

  const handleApply = async () => {
    if (selectedDevice === currentDevice) {
      return; // No change
    }

    setApplyingState('loading');
    setErrorMessage('');
    setSuccessMessage('');

    try {
      const result = await audioService.setOutputDevice(selectedDevice);

      if (result.success) {
        setCurrentDevice(selectedDevice);
        setSuccessMessage(result.message || 'Output device changed successfully');
        setApplyingState('success');

        // Clear success message after 3 seconds
        setTimeout(() => {
          setSuccessMessage('');
          setApplyingState('idle');
        }, 3000);
      } else {
        setErrorMessage(result.error || 'Failed to change output device');
        setApplyingState('error');
      }
    } catch (error) {
      console.error('Failed to set output device:', error);
      setErrorMessage(error instanceof Error ? error.message : 'Failed to change output device');
      setApplyingState('error');
    }
  };

  const handleCancel = () => {
    setSelectedDevice(currentDevice);
    setErrorMessage('');
    setSuccessMessage('');
  };

  const loadInputDevices = async () => {
    setInputLoadingState('loading');

    try {
      // Load available input devices
      const available = await audioService.getInputDevices();
      setAvailableInputDevices(available);

      // Load configured input devices
      const configured = await audioService.getConfiguredInputDevices();
      setConfiguredInputDevices(configured);

      // Initialize editing names
      const names: Record<string, string> = {};
      configured.forEach(device => {
        names[device.hw_id] = device.custom_name;
      });
      setEditingNames(names);

      setInputLoadingState('success');
    } catch (error) {
      console.error('Failed to load input devices:', error);
      setInputLoadingState('error');
    }
  };

  const isInputDeviceEnabled = (hwId: string): boolean => {
    const configured = configuredInputDevices.find(d => d.hw_id === hwId);
    return configured?.enabled || false;
  };

  const getInputDeviceCustomName = (hwId: string): string => {
    const configured = configuredInputDevices.find(d => d.hw_id === hwId);
    return configured?.custom_name || '';
  };

  const handleInputDeviceToggle = async (device: AudioDevice, enabled: boolean) => {
    try {
      if (enabled) {
        // Enable device - add with default name
        await audioService.addOrUpdateInputDevice(
          device.hw_id,
          device.friendly_name,
          true
        );
      } else {
        // Disable device - just toggle off
        await audioService.addOrUpdateInputDevice(
          device.hw_id,
          undefined,
          false
        );
      }

      // Reload devices
      await loadInputDevices();
    } catch (error) {
      console.error('Failed to toggle input device:', error);
      alert('Failed to toggle input device');
    }
  };

  const handleInputDeviceNameChange = (hwId: string, name: string) => {
    setEditingNames(prev => ({
      ...prev,
      [hwId]: name
    }));
  };

  const handleApplyInputDeviceName = async (hwId: string) => {
    const newName = editingNames[hwId];
    if (!newName) return;

    try {
      await audioService.addOrUpdateInputDevice(hwId, newName, undefined);
      await loadInputDevices();
    } catch (error) {
      console.error('Failed to update input device name:', error);
      alert('Failed to update device name');
    }
  };

  const toggleInputDeviceExpanded = (hwId: string) => {
    setExpandedInputDevice(expandedInputDevice === hwId ? null : hwId);
  };

  const hasChanges = selectedDevice !== currentDevice;
  const isLoading = loadingState === 'loading' || applyingState === 'loading';

  const getDeviceIcon = (type: DeviceType) => {
    return audioService.getDeviceTypeIcon(type);
  };

  const getDeviceTypeBadge = (type: DeviceType) => {
    const label = audioService.getDeviceTypeLabel(type);
    const colors: Record<DeviceType, string> = {
      [DeviceType.BUILTIN_HEADPHONES]: 'bg-blue-500/20 text-blue-300',
      [DeviceType.BUILTIN_HDMI]: 'bg-purple-500/20 text-purple-300',
      [DeviceType.USB]: 'bg-green-500/20 text-green-300',
      [DeviceType.HAT]: 'bg-orange-500/20 text-orange-300',
      [DeviceType.OTHER]: 'bg-gray-500/20 text-gray-300',
    };

    return (
      <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[type]}`}>
        {label}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">Audio Output</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          Select the audio device for playback. Changes will restart the audio client briefly.
        </p>

        {loadingState === 'loading' && (
          <div className="flex items-center justify-center py-8">
            <div className="text-[var(--text-secondary)]">Loading devices...</div>
          </div>
        )}

        {loadingState === 'error' && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <div className="flex items-start gap-2">
              <Icon name="circle-exclamation" className="text-red-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-400">Error Loading Devices</p>
                <p className="text-sm text-red-300 mt-1">{errorMessage}</p>
                <button
                  onClick={loadDevices}
                  className="mt-2 text-sm text-red-300 hover:text-red-200 underline"
                >
                  Try Again
                </button>
              </div>
            </div>
          </div>
        )}

        {loadingState === 'success' && outputDevices.length === 0 && (
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
            <div className="flex items-start gap-2">
              <Icon name="circle-exclamation" className="text-yellow-400 mt-0.5" />
              <div>
                <p className="text-sm text-yellow-300">No audio devices found</p>
              </div>
            </div>
          </div>
        )}

        {loadingState === 'success' && outputDevices.length > 0 && (
          <div className="space-y-4">
            <div className="space-y-2">
              {outputDevices.map((device) => (
                <label
                  key={device.hw_id}
                  className={`
                    flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all
                    ${selectedDevice === device.hw_id
                      ? 'bg-[var(--accent-color)]/10 border-[var(--accent-color)]'
                      : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] hover:border-[var(--text-secondary)]'
                    }
                    ${!device.is_available ? 'opacity-50 cursor-not-allowed' : ''}
                  `}
                >
                  <input
                    type="radio"
                    name="audioDevice"
                    value={device.hw_id}
                    checked={selectedDevice === device.hw_id}
                    onChange={(e) => setSelectedDevice(e.target.value)}
                    disabled={!device.is_available || isLoading}
                    className="w-4 h-4 text-[var(--accent-color)] focus:ring-[var(--accent-color)]"
                  />
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Icon name={getDeviceIcon(device.type)} className="text-[var(--text-secondary)] flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {device.friendly_name}
                        </span>
                        {getDeviceTypeBadge(device.type)}
                      </div>
                      <span className="text-xs text-[var(--text-secondary)] font-mono">
                        {device.hw_id}
                      </span>
                    </div>
                    {currentDevice === device.hw_id && (
                      <span className="text-xs text-green-400 font-medium flex-shrink-0">
                        Current
                      </span>
                    )}
                  </div>
                </label>
              ))}
            </div>

            {hasChanges && (
              <div className="flex items-center gap-2 pt-2">
                <button
                  onClick={handleApply}
                  disabled={isLoading}
                  className="px-4 py-2 bg-[var(--accent-color)] text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {applyingState === 'loading' ? (
                    <>
                      <Icon name="spinner" className="animate-spin" />
                      <span>Applying...</span>
                    </>
                  ) : (
                    <span>Apply Changes</span>
                  )}
                </button>
                <button
                  onClick={handleCancel}
                  disabled={isLoading}
                  className="px-4 py-2 bg-[var(--bg-tertiary)] text-[var(--text-secondary)] rounded-lg hover:bg-[var(--bg-primary)] disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
              </div>
            )}

            {successMessage && (
              <div className="p-3 bg-green-500/10 border border-green-500/20 rounded-lg">
                <div className="flex items-start gap-2">
                  <Icon name="circle-check" className="text-green-400 mt-0.5" />
                  <p className="text-sm text-green-300">{successMessage}</p>
                </div>
              </div>
            )}

            {errorMessage && applyingState === 'error' && (
              <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
                <div className="flex items-start gap-2">
                  <Icon name="circle-exclamation" className="text-red-400 mt-0.5" />
                  <p className="text-sm text-red-300">{errorMessage}</p>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="pt-4 border-t border-[var(--border-color)]">
        <div className="flex items-center gap-2 mb-2">
          <h3 className="text-lg font-semibold text-[var(--text-primary)]">Audio Input</h3>
          <span className="px-2 py-0.5 text-xs font-semibold bg-yellow-500/20 text-yellow-400 rounded border border-yellow-500/30">
            BETA
          </span>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          Enable input devices to create Snapcast streams for audio capture. Each enabled device will be available as a stream source.
        </p>
        <div className="mb-4 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
          <div className="flex items-start gap-2">
            <Icon name="circle-info" className="text-yellow-400 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-yellow-300">
              <p className="font-medium">Beta Feature - Testing Required</p>
              <p className="text-xs text-yellow-300/80 mt-1">
                This feature has not been fully tested with physical audio input devices. Please report any issues you encounter.
              </p>
            </div>
          </div>
        </div>

        {inputLoadingState === 'loading' && (
          <div className="flex items-center justify-center py-8">
            <div className="text-[var(--text-secondary)]">Loading input devices...</div>
          </div>
        )}

        {inputLoadingState === 'error' && (
          <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <div className="flex items-start gap-2">
              <Icon name="circle-exclamation" className="text-red-400 mt-0.5" />
              <div>
                <p className="text-sm font-medium text-red-400">Error Loading Input Devices</p>
                <button
                  onClick={loadInputDevices}
                  className="mt-2 text-sm text-red-300 hover:text-red-200 underline"
                >
                  Try Again
                </button>
              </div>
            </div>
          </div>
        )}

        {inputLoadingState === 'success' && availableInputDevices.length === 0 && (
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/20 rounded-lg">
            <div className="flex items-start gap-2">
              <Icon name="circle-exclamation" className="text-yellow-400 mt-0.5" />
              <div>
                <p className="text-sm text-yellow-300">No input devices found</p>
                <p className="text-xs text-yellow-300/80 mt-1">
                  Make sure your microphone or audio input device is connected
                </p>
              </div>
            </div>
          </div>
        )}

        {inputLoadingState === 'success' && availableInputDevices.length > 0 && (
          <div className="space-y-2">
            {availableInputDevices.map((device) => {
              const isEnabled = isInputDeviceEnabled(device.hw_id);
              const customName = getInputDeviceCustomName(device.hw_id);
              const isExpanded = expandedInputDevice === device.hw_id;
              const editingName = editingNames[device.hw_id] || customName || device.friendly_name;
              const nameChanged = editingName !== customName;

              return (
                <div
                  key={device.hw_id}
                  className="bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg overflow-hidden"
                >
                  {/* Header */}
                  <div className="flex items-center gap-3 p-3">
                    {/* Left: Icon + Name */}
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <Icon
                        name="microphone"
                        className="text-[var(--text-secondary)] flex-shrink-0 text-xl"
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                            {device.friendly_name}
                          </span>
                          {getDeviceTypeBadge(device.type)}
                        </div>
                        <span className="text-xs text-[var(--text-secondary)] font-mono">
                          {device.hw_id}
                        </span>
                      </div>
                    </div>

                    {/* Right: Toggle + Chevron */}
                    <div className="flex items-center gap-3 flex-shrink-0">
                      <div className="relative">
                        <input
                          type="checkbox"
                          className="sr-only"
                          checked={isEnabled}
                          onChange={(e) => handleInputDeviceToggle(device, e.target.checked)}
                          id={`input-toggle-${device.hw_id}`}
                        />
                        <label
                          htmlFor={`input-toggle-${device.hw_id}`}
                          className={`block w-12 h-6 rounded-full transition cursor-pointer ${
                            isEnabled ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'
                          }`}
                        >
                          <div
                            className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${
                              isEnabled ? 'translate-x-6' : ''
                            }`}
                          ></div>
                        </label>
                      </div>
                      {isEnabled && (
                        <button
                          onClick={() => toggleInputDeviceExpanded(device.hw_id)}
                          className="text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
                        >
                          <Icon
                            name={isExpanded ? 'chevron-up' : 'chevron-down'}
                            className="text-lg"
                          />
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded Configuration */}
                  {isEnabled && isExpanded && (
                    <div className="mt-2 ml-14 mr-3 mb-3 space-y-3">
                      <div>
                        <label className="block text-sm text-[var(--text-secondary)] mb-1">
                          Stream Name
                        </label>
                        <div className="relative">
                          <input
                            type="text"
                            value={editingName}
                            onChange={(e) => handleInputDeviceNameChange(device.hw_id, e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && handleApplyInputDeviceName(device.hw_id)}
                            className="w-full px-3 py-2 pr-20 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--accent-color)]"
                            placeholder={device.friendly_name}
                          />
                          {nameChanged && (
                            <button
                              onClick={() => handleApplyInputDeviceName(device.hw_id)}
                              className="absolute right-2 top-1/2 -translate-y-1/2 px-3 py-1 text-xs bg-[var(--accent-color)] text-white rounded hover:opacity-80"
                            >
                              Apply
                            </button>
                          )}
                        </div>
                        {nameChanged && (
                          <p className="text-xs text-amber-500 mt-1">
                            Pending changes - press Enter or click Apply
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
