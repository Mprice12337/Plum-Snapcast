/**
 * Integrations Service
 * Handles API calls for controlling integration services (start/stop, config updates)
 */

const API_BASE = `${window.location.protocol}//${window.location.hostname}:${window.location.port}/api/integrations`;

/**
 * AirPlay Control
 */
export const airplayService = {
  /**
   * Enable AirPlay service
   */
  async enable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/airplay/enable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to enable AirPlay' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to enable AirPlay:', error);
      throw error;
    }
  },

  /**
   * Disable AirPlay service
   */
  async disable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/airplay/disable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to disable AirPlay' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to disable AirPlay:', error);
      throw error;
    }
  },

  /**
   * Get AirPlay service status
   */
  async getStatus(): Promise<{ running: boolean; status: string; error?: string }> {
    try {
      const response = await fetch(`${API_BASE}/airplay/status`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get AirPlay status:', error);
      throw error;
    }
  },

  /**
   * Update AirPlay device name
   */
  async updateDeviceName(deviceName: string): Promise<{ success: boolean; message: string; deviceName?: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/airplay/device-name`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ deviceName }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to update device name' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to update AirPlay device name:', error);
      throw error;
    }
  },
};

/**
 * Bluetooth Control
 */
export const bluetoothService = {
  /**
   * Enable Bluetooth services
   */
  async enable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/bluetooth/enable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to enable Bluetooth' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to enable Bluetooth:', error);
      throw error;
    }
  },

  /**
   * Disable Bluetooth services
   */
  async disable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/bluetooth/disable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to disable Bluetooth' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to disable Bluetooth:', error);
      throw error;
    }
  },

  /**
   * Get Bluetooth service status
   */
  async getStatus(): Promise<{ running: boolean; status: string; error?: string }> {
    try {
      const response = await fetch(`${API_BASE}/bluetooth/status`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get Bluetooth status:', error);
      throw error;
    }
  },

  /**
   * Update Bluetooth device name
   */
  async updateDeviceName(deviceName: string): Promise<{ success: boolean; message: string; deviceName?: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/bluetooth/device-name`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ deviceName }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to update device name' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to update Bluetooth device name:', error);
      throw error;
    }
  },

  /**
   * Update Bluetooth settings (auto-pair and/or discoverable)
   */
  async updateSettings(settings: { autoPair?: boolean; discoverable?: boolean }): Promise<{ success: boolean; message: string; autoPair?: boolean; discoverable?: boolean; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/bluetooth/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to update settings' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to update Bluetooth settings:', error);
      throw error;
    }
  },
};

/**
 * Spotify Control
 */
export const spotifyService = {
  /**
   * Enable Spotify service
   */
  async enable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/spotify/enable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to enable Spotify' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to enable Spotify:', error);
      throw error;
    }
  },

  /**
   * Disable Spotify service
   */
  async disable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/spotify/disable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to disable Spotify' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to disable Spotify:', error);
      throw error;
    }
  },

  /**
   * Get Spotify service status
   */
  async getStatus(): Promise<{ running: boolean; status: string; error?: string }> {
    try {
      const response = await fetch(`${API_BASE}/spotify/status`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get Spotify status:', error);
      throw error;
    }
  },

  /**
   * Update Spotify device name
   */
  async updateDeviceName(deviceName: string): Promise<{ success: boolean; message: string; deviceName?: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/spotify/device-name`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ deviceName }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to update device name' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to update Spotify device name:', error);
      throw error;
    }
  },
};

/**
 * DLNA Control
 */
export const dlnaService = {
  /**
   * Enable DLNA service
   */
  async enable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/dlna/enable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to enable DLNA' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to enable DLNA:', error);
      throw error;
    }
  },

  /**
   * Disable DLNA service
   */
  async disable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/dlna/disable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to disable DLNA' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to disable DLNA:', error);
      throw error;
    }
  },

  /**
   * Get DLNA service status
   */
  async getStatus(): Promise<{ running: boolean; status: string; error?: string }> {
    try {
      const response = await fetch(`${API_BASE}/dlna/status`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get DLNA status:', error);
      throw error;
    }
  },

  /**
   * Update DLNA device name
   */
  async updateDeviceName(deviceName: string): Promise<{ success: boolean; message: string; deviceName?: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/dlna/device-name`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ deviceName }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to update device name' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to update DLNA device name:', error);
      throw error;
    }
  },
};

/**
 * Plexamp Control
 */
export const plexampService = {
  /**
   * Enable Plexamp service
   */
  async enable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/plexamp/enable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to enable Plexamp' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to enable Plexamp:', error);
      throw error;
    }
  },

  /**
   * Disable Plexamp service
   */
  async disable(): Promise<{ success: boolean; message: string; details?: string }> {
    try {
      const response = await fetch(`${API_BASE}/plexamp/disable`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: 'Failed to disable Plexamp' }));
        throw new Error(errorData.message || `HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to disable Plexamp:', error);
      throw error;
    }
  },

  /**
   * Get Plexamp service status
   */
  async getStatus(): Promise<{ running: boolean; status: string; error?: string }> {
    try {
      const response = await fetch(`${API_BASE}/plexamp/status`);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error('Failed to get Plexamp status:', error);
      throw error;
    }
  },
};
