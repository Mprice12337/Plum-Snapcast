import React, {useState, useEffect} from 'react';
import type {Server, Settings as SettingsType} from '../../types';
import {Switch} from '../Switch';
import {ServerManager} from '../ServerManager';
import {federationService} from '../../services/federationService';

interface SnapcastTabProps {
  settings: SettingsType;
  onSettingsChange: (newSettings: SettingsType) => void;
}

export const SnapcastTab: React.FC<SnapcastTabProps> = ({
  settings,
  onSettingsChange,
}) => {
  const [servers, setServers] = useState<Server[]>([]);

  useEffect(() => {
    if (settings.federation.enabled) {
      const fetchServers = async () => {
        const serverList = await federationService.getServers();
        setServers(serverList);
      };
      fetchServers();
    } else {
      setServers([]);
    }
  }, [settings.federation.enabled]);

  const handleFederationChange = (key: keyof SettingsType['federation'], value: boolean | string) => {
    onSettingsChange({
      ...settings,
      federation: {
        ...settings.federation,
        [key]: value,
      },
    });
  };

  const handleDisplayChange = (key: keyof SettingsType['display'], value: boolean) => {
    onSettingsChange({
      ...settings,
      display: {
        ...settings.display,
        [key]: value,
      },
    });
  };

  const handleAddServer = async (host: string, port: number, name: string) => {
    const result = await federationService.addServer(host, port, name);
    if (result.success && result.server) {
      setServers([...servers, result.server]);
    }
    return result;
  };

  const handleRemoveServer = async (serverId: string) => {
    const result = await federationService.removeServer(serverId);
    if (result.success) {
      setServers(servers.filter(s => s.id !== serverId));
    }
    return result;
  };

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-base font-semibold text-[var(--text-primary)] mb-4">
          Multi-Server Federation
        </h3>
        <p className="text-sm text-[var(--text-muted)] mb-6">
          Control multiple Snapcast servers from a single interface
        </p>
      </div>

      <div className="space-y-4">
        <Switch
          label="Multi-Server Control"
          checked={settings.federation.enabled}
          onChange={(val) => handleFederationChange('enabled', val)}
          icon="fa-network-wired"
        />

        {settings.federation.enabled && (
          <>
            <div className="pl-8 space-y-4">
              <Switch
                label="Auto-Discover Servers"
                checked={settings.federation.autoDiscover}
                onChange={(val) => handleFederationChange('autoDiscover', val)}
                icon="fa-radar"
              />

              <div>
                <label className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
                  Local Server Name
                </label>
                <input
                  type="text"
                  value={settings.federation.localServerName}
                  onChange={(e) => handleFederationChange('localServerName', e.target.value)}
                  placeholder="e.g., Main Server"
                  className="w-full px-3 py-2 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-color)]"
                />
                <p className="text-xs text-[var(--text-muted)] mt-1">
                  This name will be visible to other servers on your network
                </p>
              </div>

              <div>
                <ServerManager
                  servers={servers}
                  onAddServer={handleAddServer}
                  onRemoveServer={handleRemoveServer}
                />
              </div>
            </div>
          </>
        )}
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-4">Display Options</h4>
        <div className="space-y-4">
          <Switch
            label="Show Offline Devices"
            checked={settings.display.showOfflineDevices}
            onChange={(val) => handleDisplayChange('showOfflineDevices', val)}
            icon="fa-eye"
          />
          <p className="text-xs text-[var(--text-muted)] pl-8 -mt-2">
            Display devices that are currently disconnected or unreachable
          </p>
        </div>
      </div>

      <div className="pt-4 mt-6 border-t border-[var(--border-color)]">
        <h4 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          About Federation
        </h4>
        <p className="text-xs text-[var(--text-muted)]">
          Federation allows you to control multiple Snapcast servers from one interface. When enabled,
          you can see and control clients across all connected servers, making it easy to manage
          multi-room audio across different locations.
        </p>
      </div>
    </div>
  );
};
