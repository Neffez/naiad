import {
  DndContext,
  type DragEndEvent,
  KeyboardSensor,
  MouseSensor,
  TouchSensor,
  closestCenter,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  SortableContext,
  type SortingStrategy,
  arrayMove,
  rectSortingStrategy,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import type { CSSProperties, ReactNode } from 'react'

interface SortableItemProps {
  id: string
  children: ReactNode
}

function SortableItem({ id, children }: SortableItemProps) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id })

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    cursor: isDragging ? 'grabbing' : 'grab',
    // While dragging, lift the item above its siblings.
    zIndex: isDragging ? 20 : undefined,
    opacity: isDragging ? 0.92 : 1,
    boxShadow: isDragging ? '0 18px 40px rgba(0,0,0,0.45)' : undefined,
    borderRadius: 'var(--n-r-lg)',
    // Let the grid stretch the wrapper so cards using height:100% still fill the cell.
    display: 'flex',
    flexDirection: 'column',
  }

  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
      {children}
    </div>
  )
}

interface SortableGridProps<T extends { id: string }> {
  /** Items in their current (already-ordered) display order. */
  items: T[]
  /** Called with the full list of IDs in the new order after a drag completes. */
  onReorder: (ids: string[]) => void
  /** Renders a single item's card content (without a wrapping key — handled internally). */
  renderItem: (item: T) => ReactNode
  /** Styles applied to the container holding the sortable items (e.g. the grid definition). */
  style?: CSSProperties
  /** Layout strategy — defaults to a 2D grid; pass verticalListSortingStrategy for stacked lists. */
  strategy?: SortingStrategy
}

/**
 * A drag-and-drop sortable container. On desktop a small drag distance starts
 * the drag (so clicks on buttons still work); on touch a long press activates
 * it (so the list can still be scrolled). Keyboard reordering is supported via
 * the sortable keyboard coordinate getter.
 */
export function SortableGrid<T extends { id: string }>({
  items,
  onReorder,
  renderItem,
  style,
  strategy = rectSortingStrategy,
}: SortableGridProps<T>) {
  const sensors = useSensors(
    useSensor(MouseSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 250, tolerance: 8 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const ids = items.map((item) => item.id)

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIndex = ids.indexOf(String(active.id))
    const newIndex = ids.indexOf(String(over.id))
    if (oldIndex === -1 || newIndex === -1) return
    onReorder(arrayMove(ids, oldIndex, newIndex))
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={ids} strategy={strategy}>
        <div style={style}>
          {items.map((item) => (
            <SortableItem key={item.id} id={item.id}>
              {renderItem(item)}
            </SortableItem>
          ))}
        </div>
      </SortableContext>
    </DndContext>
  )
}
