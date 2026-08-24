/**
 * Copyright (c) 2024 ipyelk contributors.
 * Distributed under the terms of the Modified BSD License.
 */
import { Action, HoverFeedbackAction } from 'sprotty-protocol';

import {
  MouseListener,
  SModelElementImpl,
  findParentByFeature,
  isHoverable,
} from 'sprotty';

import { DiagramTool } from './tool';

/**
 * A mouse listener that is aware of prior mouse dragging.
 *
 * Therefore, this listener distinguishes between mouse up events after dragging and
 * mouse up events without prior dragging. Subclasses may override the methods
 * `draggingMouseUp` and/or `nonDraggingMouseUp` to react to only these specific kinds
 * of mouse up events.
 */
export class DragAwareMouseListener extends MouseListener {
  private isMouseDown: boolean = false;
  private isMouseDrag: boolean = false;

  mouseDown(target: SModelElementImpl, event: MouseEvent): Action[] {
    this.isMouseDown = true;
    return [];
  }

  mouseMove(target: SModelElementImpl, event: MouseEvent): Action[] {
    if (this.isMouseDown) {
      this.isMouseDrag = true;
    }
    return [];
  }

  mouseUp(element: SModelElementImpl, event: MouseEvent): Action[] {
    this.isMouseDown = false;
    if (this.isMouseDrag) {
      this.isMouseDrag = false;
      return this.draggingMouseUp(element, event);
    }

    return this.nonDraggingMouseUp(element, event);
  }

  nonDraggingMouseUp(element: SModelElementImpl, event: MouseEvent): Action[] {
    return [];
  }

  draggingMouseUp(element: SModelElementImpl, event: MouseEvent): Action[] {
    return [];
  }
}

export class DragAwareHoverMouseListener extends DragAwareMouseListener {
  constructor(
    protected elementTypeId: string,
    protected tool: DiagramTool,
  ) {
    super();
  }

  // LOCAL PATCH (sysml2-experiments hover parity): attribute hover feedback
  // to the nearest HOVERABLE ancestor -- exactly how sprotty core's
  // HoverMouseListener and this file's select tool (findParentByFeature)
  // resolve their targets.  The raw target is whatever element the pointer
  // sits on: for a node's LABELS (package folder tab, accept/send badges,
  // title text) that is the label itself, which has no
  // hoverFeedbackFeature, so HoverFeedbackCommand silently dropped the
  // action and hovering a label gave no feedback at all.  Walking up finds
  // the owning node/edge/port, so hovering any part of a shape highlights
  // the WHOLE shape -- hover now matches selection's attribution.
  mouseOver(target: SModelElementImpl, event: MouseEvent): Action[] {
    const hoverTarget = findParentByFeature(target, isHoverable);
    if (hoverTarget === undefined) {
      return [];
    }
    return [
      HoverFeedbackAction.create({
        mouseoverElement: hoverTarget.id,
        mouseIsOver: true,
      }),
    ];
  }

  mouseOut(target: SModelElementImpl, event: MouseEvent): (Action | Promise<Action>)[] {
    const hoverTarget = findParentByFeature(target, isHoverable);
    if (hoverTarget === undefined) {
      return [];
    }
    return [
      HoverFeedbackAction.create({
        mouseoverElement: hoverTarget.id,
        mouseIsOver: false,
      }),
    ];
  }
}
