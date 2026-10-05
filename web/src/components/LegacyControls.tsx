import type { PlayerApi } from '../usePlayer'
import { TrackSelector } from './TrackSelector'
import { TransposeSelector } from './TransposeSelector'
import { HardwareStatus } from './HardwareStatus'
import { DrumPanel } from './DrumPanel'

export function LegacyControls({ player }: { player: PlayerApi }) {
  const { state } = player
  return <div className="manual-controls"><section className="selectors">
        <TrackSelector
          metadata={player.metadata}
          selected={state?.track ?? null}
          onSelect={player.selectTrack}
          label="FDD Track"
        />

        <TrackSelector
          metadata={player.metadata}
          selected={state?.drum.midiTrack ?? null}
          onSelect={(index) => player.selectDrumTrack(index < 0 ? null : index)}
          label="VHS Drum Track"
          allowNone
          noneLabel="None (bęben ręcznie)"
        />

        <TransposeSelector
          value={state?.transpose ?? 'auto'}
          range={state?.range ?? null}
          onSelect={player.selectTranspose}
          label="FDD transpose"
        />

        <TransposeSelector
          value={state?.drum.transpose ?? 'auto'}
          range={state?.drum.range ?? null}
          onSelect={player.selectDrumTranspose}
          label="VHS Drum transpose"
        />

        <label className="field">
          <span className="field-label">VHS Drum strategy</span>

          <select
            value={state?.drum.strategy ?? 'highest'}
            onChange={(event) => player.selectDrumStrategy(event.target.value)}
          >
            <option value="highest">highest — najwyższa nuta (melodia)</option>
            <option value="lowest">lowest — najniższa nuta (bas)</option>
            <option value="last">last — ostatni NOTE_ON</option>
          </select>
        </label>

        <TrackSelector
          metadata={player.metadata}
          selected={state?.hdd.midiTrack ?? null}
          onSelect={(index) => player.selectHddTrack(index < 0 ? null : index)}
          label="HDD Track (perkusja)"
          allowNone
          noneLabel="None (HDD wyłączony)"
        />

        {state?.hdd.midiTrack != null && (
          <>
            <label className="field">
              <span className="field-label">HDD Note (co ma uderzać)</span>

              <select
                value={state.hdd.note ?? ''}
                onChange={(event) =>
                  player.selectHddNote(
                    event.target.value === '' ? null : Number(event.target.value),
                  )
                }
              >
                <option value="">
                  wszystkie nuty ({state.hdd.notes.reduce((sum, o) => sum + o.count, 0)})
                </option>

                {state.hdd.notes.map((option) => (
                  <option key={option.note} value={option.note}>
                    {option.name} ({option.note}) · {option.count}×
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span className="field-label">HDD Gęstość</span>

              <select
                value={state.hdd.rate ?? ''}
                onChange={(event) =>
                  player.selectHddRate(
                    event.target.value === '' ? null : Number(event.target.value),
                  )
                }
              >
                <option value="">bez limitu (tylko mechanika ~9/s)</option>
                <option value="4">max 4 uderzenia/s</option>
                <option value="3">max 3 uderzenia/s</option>
                <option value="2">max 2 uderzenia/s</option>
                <option value="1">max 1 uderzenie/s (half-time)</option>
                <option value="0.5">max 1 na 2 s</option>
              </select>
            </label>

            <p className="hdd-status">
              HDD: {state.hdd.midiTrackName} ·{' '}
              {state.hdd.note == null
                ? 'wszystkie nuty'
                : state.hdd.notes.find((o) => o.note === state.hdd.note)?.name ??
                  `nuta ${state.hdd.note}`}{' '}
              · {state.hdd.count} uderzeń
              {state.hdd.busy ? ' · ⏵ uderzenie' : ''}
            </p>
          </>
        )}
      </section><HardwareStatus
        hardware={state?.hardware ?? null}
        ports={player.ports}
        onReconnect={player.reconnect}
        onHome={player.home}
      />

      <DrumPanel
        drum={state?.drum ?? null}
        onStart={player.startDrum}
        onStop={player.stopDrum}
        onPwm={player.setDrum}
        onTone={player.setDrumTone}
      />

</div>
}
