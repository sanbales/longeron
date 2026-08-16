/**
 * Copyright (c) 2024 ipyelk contributors.
 * Distributed under the terms of the Modified BSD License.
 */
import { describe, expect, it } from 'vitest';

import { layoutErrorMessage } from './layout_widget_util';

describe('layoutErrorMessage', () => {
  it('wraps an error into a kernel error message', () => {
    const msg = layoutErrorMessage(new Error('elk exploded'));
    expect(msg.action).toBe('error');
    expect(msg.error).toContain('elk exploded');
  });
});
