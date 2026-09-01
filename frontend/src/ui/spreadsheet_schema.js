/** Shared column schema for the 3D and cadnano strand spreadsheets. */
const COLUMN_DEFINITIONS = Object.freeze([
  { key: 'id',       label: 'ID',          toggleable: false, editable: false },
  { key: 'name',     label: 'Name',        toggleable: false, editable: true },
  { key: 'start',    label: 'Start',       toggleable: false, editable: false },
  { key: 'end',      label: 'End',         toggleable: false, editable: false },
  // Strand visibility is a 3D-renderer capability, so the editor omits only
  // this column while sharing every sequence-data column below.
  { key: 'show',     label: 'Show',        toggleable: false, editable: false, viewerOnly: true },
  { key: 'ovhg_5p',  label: "5' Overhang", toggleable: true,  editable: true,  resizable: true },
  { key: 'sequence', label: 'Sequence',    toggleable: true,  editable: false, resizable: true },
  { key: 'ovhg_3p',  label: "3' Overhang", toggleable: true,  editable: true,  resizable: true },
  { key: 'group',    label: 'Group',       toggleable: true,  editable: false },
  { key: 'color',    label: 'Color',       toggleable: true,  editable: false },
  { key: 'length',   label: 'Length',      toggleable: true,  editable: false },
  { key: 'notes',    label: 'Notes',       toggleable: true,  editable: true },
])

export function spreadsheetColumns({ includeViewerOnly = false } = {}) {
  return COLUMN_DEFINITIONS.filter(column => includeViewerOnly || !column.viewerOnly)
}
