import React, {useState, useEffect} from 'react';
import type {Settings as SettingsType} from '../../types';
import {audioService, type AudioDevice, DeviceType} from '../../services/audioService';
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

  // Load output devices on mount
  useEffect(() => {
    loadDevices();
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
      setCurrentDevice(current.hwId);
      setSelectedDevice(current.hwId);

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
                  key={device.hwId}
                  className={`
                    flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all
                    ${selectedDevice === device.hwId
                      ? 'bg-[var(--accent-color)]/10 border-[var(--accent-color)]'
                      : 'bg-[var(--bg-tertiary)] border-[var(--border-color)] hover:border-[var(--text-secondary)]'
                    }
                    ${!device.isAvailable ? 'opacity-50 cursor-not-allowed' : ''}
                  `}
                >
                  <input
                    type="radio"
                    name="audioDevice"
                    value={device.hwId}
                    checked={selectedDevice === device.hwId}
                    onChange={(e) => setSelectedDevice(e.target.value)}
                    disabled={!device.isAvailable || isLoading}
                    className="w-4 h-4 text-[var(--accent-color)] focus:ring-[var(--accent-color)]"
                  />
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    <Icon name={getDeviceIcon(device.type)} className="text-[var(--text-secondary)] flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-medium text-[var(--text-primary)] truncate">
                          {device.friendlyName}
                        </span>
                        {getDeviceTypeBadge(device.type)}
                      </div>
                      <span className="text-xs text-[var(--text-secondary)] font-mono">
                        {device.hwId}
                      </span>
                    </div>
                    {currentDevice === device.hwId && (
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
        <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">Audio Input</h3>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          Input device configuration will be available in a future update.
        </p>
        <div className="p-4 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg">
          <div className="flex items-center gap-2">
            <Icon name="circle-info" className="text-[var(--text-secondary)]" />
            <span className="text-sm text-[var(--text-secondary)]">
              Coming soon: Configure input devices for announcements and audio streaming
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
