/**
 * Copyright (c) 2021 Dane Freeman.
 * Distributed under the terms of the Modified BSD License.
 */

/*******************************************************************************
 * Copyright (c) 2017 TypeFox GmbH (http://www.typefox.io) and others.
 * All rights reserved. This program and the accompanying materials
 * are made available under the terms of the Eclipse Public License v1.0
 * which accompanies this distribution, and is available at
 * http://www.eclipse.org/legal/epl-v10.html
 *******************************************************************************/

/** @jsx svg */
import { VNode } from 'snabbdom';

import { injectable } from 'inversify';

import { Point, angleOfPoint, toDegrees } from 'sprotty-protocol';

import {
  PolylineEdgeView,
  SRoutableElementImpl,
  getAbsoluteRouteBounds,
  setClass,
  svg,
} from 'sprotty';

import { ElkModelRenderer } from '../renderer';
import { SElkConnectorSymbol } from '../json/symbols';
import { ElkEdge, ElkJunction } from '../sprotty-model';

import { CircularNodeView, validCanvasBounds } from './base';

@injectable()
export class JunctionView extends CircularNodeView {
  render(node: ElkJunction, context: ElkModelRenderer): VNode {
    const radius = this.getRadius(node);
    return (
      <g>
        <circle class-elkjunction={true} r={radius}></circle>
      </g>
    );
  }

  protected getRadius(node: ElkJunction): number {
    return 2;
  }
}

/**
 * Zero-length route chords make `angleOfPoint` return 0 (atan2(0, 0)):
 * elkjs SPLINES sections duplicate control points at the section knots, so
 * the naive "adjacent segment" tangent flipped end symbols 180 degrees on
 * any right-to-left end (the head rendered pointing INTO the target node).
 * Points closer together than this are never used as a tangent reference.
 */
const MIN_TANGENT_LENGTH = 1e-3;

/**
 * Angle (radians) of the route at one of its ends, pointing from that end
 * point INTO the edge.
 *
 * Instead of the adjacent route segment -- which may be a zero-length
 * spline chord (see MIN_TANGENT_LENGTH) or a stub shorter than the symbol
 * riding it (elk POLYLINE bends within a few px of the node: a 12px
 * membership diamond then straddles the bend, drawn axis-aligned while the
 * visible shaft leaves diagonally) -- the tangent is the chord from the
 * end point to the route point `reach` px along the route. That is exact
 * on straight and orthogonal ends (the layout keeps bends out of a
 * symbol's footprint there) and the symbol's average direction otherwise.
 */
export function routeEndAngle(
  route: Point[],
  end: 'source' | 'target',
  reach: number,
): number {
  const points = end === 'source' ? route : [...route].reverse();
  const origin = points[0];
  const distance = Math.max(reach, MIN_TANGENT_LENGTH);
  let travelled = 0;
  for (let i = 1; i < points.length; i++) {
    const segment = Point.euclideanDistance(points[i - 1], points[i]);
    if (segment >= MIN_TANGENT_LENGTH && travelled + segment >= distance) {
      const t = Math.min((distance - travelled) / segment, 1);
      const ref = {
        x: points[i - 1].x + (points[i].x - points[i - 1].x) * t,
        y: points[i - 1].y + (points[i].y - points[i - 1].y) * t,
      };
      return angleOfPoint({ x: ref.x - origin.x, y: ref.y - origin.y });
    }
    travelled += segment;
  }
  // route shorter than the reach: fall back to the farthest distinct point
  for (let i = points.length - 1; i > 0; i--) {
    const p = points[i];
    if (Point.euclideanDistance(origin, p) >= MIN_TANGENT_LENGTH) {
      return angleOfPoint({ x: p.x - origin.x, y: p.y - origin.y });
    }
  }
  return 0;
}

/**
 * How far back along the shaft a connector symbol reaches: its
 * `path_offset` pulls the line end from under the symbol body, so its
 * length is exactly the footprint the symbol covers.
 */
export function symbolReach(connection?: SElkConnectorSymbol): number {
  const offset = connection?.path_offset;
  return offset ? Math.sqrt(offset.x * offset.x + offset.y * offset.y) : 0;
}

/**
 * Number of interior route points within `reach` (arc length) of the given
 * route end. The shaft is trimmed by the end symbols' path offsets, so
 * bends this close to an end would make the drawn path double back beneath
 * the symbol (elk polyline stubs, elkjs spline knot duplicates); the
 * renderer drops them from the path.
 */
export function coveredRoutePoints(
  route: Point[],
  end: 'source' | 'target',
  reach: number,
): number {
  const points = end === 'source' ? route : [...route].reverse();
  let travelled = 0;
  let covered = 0;
  for (let i = 1; i < points.length - 1; i++) {
    travelled += Point.euclideanDistance(points[i - 1], points[i]);
    if (travelled >= reach) {
      break;
    }
    covered += 1;
  }
  return covered;
}

@injectable()
export class ElkEdgeView extends PolylineEdgeView {
  isVisible(
    model: Readonly<SRoutableElementImpl>,
    route: Point[],
    context: ElkModelRenderer,
  ): boolean {
    if (context.targetKind === 'hidden') {
      // Don't hide any element for hidden rendering
      return true;
    }
    if (route.length === 0) {
      // We should hide only if we know the element's route
      return true;
    }

    const canvasBounds = model.root.canvasBounds;
    if (!validCanvasBounds(canvasBounds)) {
      // only hide if the canvas's size is set
      return true;
    }
    const ab = getAbsoluteRouteBounds(model, route);
    return (
      ab.x <= canvasBounds.width &&
      ab.x + ab.width >= 0 &&
      ab.y <= canvasBounds.height &&
      ab.y + ab.height >= 0
    );
  }

  render(edge: Readonly<ElkEdge>, context: ElkModelRenderer): VNode | undefined {
    const router = this.edgeRouterRegistry.get(edge.routerKind);
    const route = router.route(edge);
    if (route.length === 0) {
      return this.renderDanglingEdge('Cannot compute route', edge, context);
    }
    if (!this.isVisible(edge, route, context)) {
      if (edge.children.length === 0) {
        return undefined;
      }
      // The children of an edge are not necessarily inside the bounding box of the route,
      // so we need to render a group to ensure the children have a chance to be rendered.
      return <g>{context.renderChildren(edge, { route })}</g>;
    }

    return (
      <g class-elkedge={true} class-mouseover={edge.hoverFeedback}>
        {this.renderLine(edge, route, context)}
        {this.renderAdditionals(edge, route, context)}
        {context.renderChildren(edge, { route })}
      </g>
    );
  }

  protected renderLine(
    edge: ElkEdge,
    segments: Point[],
    context: ElkModelRenderer,
  ): VNode {
    const startId = edge?.properties?.shape?.start;
    const endId = edge?.properties?.shape?.end;
    const startReach = symbolReach(context.getConnector(startId));
    const endReach = symbolReach(context.getConnector(endId));
    let r = routeEndAngle(segments, 'source', startReach);
    let r2 = routeEndAngle(segments, 'target', endReach);

    let start = this.getPathOffset(startId, context, r);
    let end = this.getPathOffset(endId, context, r2);

    // interior points beneath an end symbol would make the trimmed shaft
    // double back under it -- skip them
    const first = 1 + coveredRoutePoints(segments, 'source', startReach);
    const last = segments.length - 2 - coveredRoutePoints(segments, 'target', endReach);

    const firstPoint = segments[0];
    let path = `M ${firstPoint.x - start.x},${firstPoint.y - start.y}`;
    for (let i = first; i <= last; i++) {
      const p = segments[i];
      path += ` L ${p.x},${p.y}`;
    }
    const lastPoint = segments[segments.length - 1];
    path += ` L ${lastPoint.x - end.x}, ${lastPoint.y - end.y}`;
    return <path d={path} />;
  }

  protected getAnchorOffset(
    id: string | undefined,
    context: ElkModelRenderer,
    r: number,
  ): Point {
    let connection = context.getConnector(id);
    if (connection?.symbol_offset) {
      const p = connection.symbol_offset;
      return {
        x: p.x * Math.cos(r) - p.y * Math.sin(r),
        y: p.x * Math.sin(r) + p.y * Math.cos(r),
      };
    }
    return { x: 0, y: 0 };
  }

  protected getPathOffset(
    id: string | undefined,
    context: ElkModelRenderer,
    r: number,
  ): Point {
    let connection = context.getConnector(id);
    if (connection?.path_offset) {
      const p = connection.path_offset;
      return {
        x: p.x * Math.cos(r) - p.y * Math.sin(r),
        y: p.x * Math.sin(r) + p.y * Math.cos(r),
      };
    }

    return { x: 0, y: 0 };
  }

  protected renderAdditionals(
    edge: ElkEdge,
    segments: Point[],
    context: ElkModelRenderer,
  ): VNode[] {
    let connectors: VNode[] = [];
    let href: string;
    let correction: Point;
    let vnode: VNode;
    let start = edge?.properties?.shape?.start;
    let end = edge?.properties?.shape?.end;
    if (start) {
      const p2 = segments[0];
      let r = routeEndAngle(segments, 'source', symbolReach(context.getConnector(start)));

      correction = this.getAnchorOffset(start, context, r);

      let x = p2.x - correction.x;
      let y = p2.y - correction.y;
      href = context.hrefID(start);
      vnode = (
        <use
          href={'#' + href}
          class-elkedge-start={true}
          class-elkarrow={true}
          transform={`rotate(${toDegrees(r)} ${x} ${y}) translate(${x} ${y})`}
        />
      );
      setClass(vnode, start, true);
      connectors.push(vnode);
    }
    if (end) {
      const p2 = segments[segments.length - 1];
      let r = routeEndAngle(segments, 'target', symbolReach(context.getConnector(end)));
      correction = this.getAnchorOffset(end, context, r);

      let x = p2.x - correction.x;
      let y = p2.y - correction.y;
      href = context.hrefID(end);
      vnode = (
        <use
          href={'#' + href}
          class-elkedge-end={true}
          class-elkarrow={true}
          transform={`rotate(${toDegrees(r)} ${x} ${y}) translate(${x} ${y})`}
        />
      );
      setClass(vnode, end, true);
      connectors.push(vnode);
    }
    return connectors;
  }
}

export function angle(x0: Point, x1: Point): number {
  return toDegrees(Math.atan2(x1.y - x0.y, x1.x - x0.x));
}
