import React from 'react';

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
}

export const Switch: React.FC<SwitchProps> = ({ checked, onChange, label }) => {
  const switchId = `switch-${label.replace(/\s+/g, '-').toLowerCase()}`;

  return (
    <label htmlFor={switchId} className="flex items-center justify-between cursor-pointer p-2 rounded-lg hover:bg-[var(--bg-tertiary)]">
      <span className="text-base text-[var(--text-secondary)]">{label}</span>
      <div className="relative">
        <input
          id={switchId}
          type="checkbox"
          className="sr-only"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        <div className={`block w-12 h-6 rounded-full transition ${checked ? 'bg-[var(--accent-color)]' : 'bg-[var(--bg-tertiary-hover)]'}`}></div>
        <div
          className={`dot absolute left-1 top-1 bg-white w-4 h-4 rounded-full transition-transform ${checked ? 'translate-x-6' : ''}`}
        ></div>
      </div>
    </label>
  );
};