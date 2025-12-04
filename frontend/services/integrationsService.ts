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
