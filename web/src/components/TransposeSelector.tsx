/** Wybor trybu skladania oktawowego (pitch mapping). */

interface Props {
  value: string
  range: { minHz: number; maxHz: number } | null
  onSelect: (mode: string) => void
  label?: string
}

const MODES: Array<{ value: string; label: (range: Props['range']) => string }> = [
  {
    value: 'auto',
    label: () => 'AUTO — nuta zostaje, jeśli się mieści (mogą być skoki oktawowe)',
  },
  {
    value: 'low',
    label: (range) => `LOW ${range ? `${range.minHz}–${range.minHz * 2}` : '130–260'} Hz — bez skoków`,
  },
  {
    value: 'high',
    label: (range) => `HIGH ${range ? `${range.maxHz / 2}–${range.maxHz}` : '165–330'} Hz — bez skoków`,
  },
]

export function TransposeSelector({ value, range, onSelect, label = 'Transpose' }: Props) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>

      <select value={value} onChange={(event) => onSelect(event.target.value)}>
        {MODES.map((mode) => (
          <option key={mode.value} value={mode.value}>
            {mode.label(range)}
          </option>
        ))}
      </select>
    </label>
  )
}
