/**
 * Copyright (c) 2024 ipyelk contributors.
 * Distributed under the terms of the Modified BSD License.
 */
import { random } from 'lodash';

import { DOMWidgetModel, DOMWidgetView } from '@jupyter-widgets/base';
import { unpack_models as deserialize } from '@jupyter-widgets/base';

import { layoutErrorMessage } from './layout_widget_util';
import { ElkLabel, ElkNode } from './sprotty/json/elkgraph-json';
import { ELK_CSS, ELK_DEBUG, IRunMessage, NAME, VERSION } from './tokens';

// import { ElkNode } from './sprotty/sprotty-model';

export class ELKTextSizerModel extends DOMWidgetModel {
  static model_name = 'ELKTextSizerModel';
  static serializers = {
    ...DOMWidgetModel.serializers,
    inlet: { deserialize },
    outlet: { deserialize },
  };

  defaults() {
    let defaults = {
      ...super.defaults(),

      _model_name: ELKTextSizerModel.model_name,
      _model_module_version: VERSION,
      _view_module: NAME,
      _view_name: ELKTextSizerView.view_name,
      _view_module_version: VERSION,
      id: String(Math.random()),
      inlet: null,
      outlet: null,
    };
    return defaults;
  }

  initialize(
    attributes: any,
    options: {
      model_id: string;
      comm?: any;
      widget_manager: any;
    },
  ) {
    super.initialize(attributes, options);
    ELK_DEBUG && console.warn('ELK Test Sizer Init');
    this.on('msg:custom', this.handleMessage, this);
    ELK_DEBUG && console.warn('ELK Text Done Init');
  }

  make_container(): HTMLElement {
    const el: HTMLElement = document.createElement('div');
    const styledClass = this.get('_dom_classes').filter(
      (dc: string) => dc.indexOf('styled-widget-') === 0,
    )[0];
    el.classList.add(
      'lm-Widget',
      ELK_CSS.widget_class,
      ELK_CSS.sizer_class,
      styledClass,
    );
    const raw_css: string = this.get('namespaced_css'); //TODO should this `raw_css` string be escaped?
    el.innerHTML = `<div class="sprotty"><style>${raw_css}</style><svg class="sprotty-graph"><g></g></svg></div>`;
    return el;
  }

  /**
   * SVG Text Element for given text string
   * @param text
   */
  make_label(label: ElkLabel): SVGElement {
    ELK_DEBUG && console.warn('ELK Text Label for text', label);
    let element: SVGElement = createSVGElement('text');
    let classes: string[] = [ELK_CSS.label];
    if (label.properties?.cssClasses.length > 0) {
      classes = classes.concat(label.properties?.cssClasses.split(' '));
    }

    element.classList.add(...classes);
    element.textContent = label.text;
    ELK_DEBUG && console.warn('ELK Text Label', element);
    return element;
  }

  handleMessage(content: IRunMessage) {
    // check message and decide if should call `measure`
    switch (content.action) {
      case 'run':
        // LOCAL PATCH (sysml2-experiments): a throwing measure used to
        // reject silently inside the kernel connection's serial message
        // chain (the chain's catch swallows it) -- the kernel kept
        // re-sending `run` forever. Report it over the pipe's error
        // channel so the roundtrip fails visibly instead.
        try {
          this.measure();
        } catch (error) {
          console.error('ELK text sizer failed:', error);
          this.send(layoutErrorMessage(error));
        }
        break;
    }
  }

  /**
   * Method to take a list of texts and build SVG Text Elements to attach to the DOM
   * @param content message measure request
   */
  measure() {
    const rootNode: ElkNode = this.get('inlet')?.get('value');
    let outlet: DOMWidgetModel = this.get('outlet'); // target output
    if (rootNode == null || outlet == null) {
      // LOCAL PATCH (sysml2-experiments): a `run` request the frontend
      // cannot serve means the state this model needs never arrived --
      // jupyter-server's iopub rate limiter silently DROPS comm messages
      // under bursty load (a run-all creating two dozen diagrams on a
      // slow CI runner), so the inlet reference or its value can be
      // missing here while the kernel-side pipe waits forever on an
      // answer. Returning silently wedged the pipeline at this stage with
      // no error; instead report the stale state so the kernel re-syncs
      // (see SyncedPipe._handle_browser_msg) and the next re-sent `run`
      // finds a servable model.
      this.send(
        {
          action: 'stale',
          missing: {
            inlet: this.get('inlet') == null,
            value: rootNode == null,
            outlet: outlet == null,
          },
        },
      );
      return null;
    }
    ELK_DEBUG && console.log('Root Node:', rootNode);
    let texts: ElkLabel[] = get_labels(rootNode);

    ELK_DEBUG && console.warn('ELK Text Sizer Measure', texts);
    const el: HTMLElement = this.make_container();
    const view: SVGElement = el.getElementsByTagName('g')[0];

    const new_g: SVGElement = createSVGElement('g');
    texts.forEach((text) => {
      new_g.appendChild(this.make_label(text));
    });
    view.appendChild(new_g);

    ELK_DEBUG && console.warn('ELK Text Sizer to add node', new_g);
    ELK_DEBUG && console.warn('ELK Text Sizer node', view);

    document.body.prepend(el);

    let elements: SVGElement[] = Array.from(new_g.getElementsByTagName('text'));

    ELK_DEBUG && console.warn('Sized Text');

    // Callback to take measurements and remove element from DOM
    window.requestAnimationFrame(() => {
      // LOCAL PATCH (sysml2-experiments): a throw in this deferred
      // callback is otherwise an unhandled error nobody correlates with
      // the pipe -- report it over the error channel like the sync path.
      try {
        this.read_sizes(texts, elements);
        let output = { ...rootNode };
        output['out'] = random();
        outlet.set('value', output);
        outlet.save_changes();
      } catch (error) {
        console.error('ELK text sizer failed:', error);
        this.send(layoutErrorMessage(error));
      } finally {
        if (!ELK_DEBUG && el.parentNode) {
          document.body.removeChild(el);
        }
      }
    });
  }

  /**
   * Read the given SVG Text Elements sizes and generate TextSize Objects
   * @param texts Original list of text strings requested to size
   * @param elements List of SVG Text Elements to get their respective bounding boxes
   */
  read_sizes(labels: ElkLabel[], elements: SVGElement[]) {
    let i = 0;
    for (let element of elements) {
      ELK_DEBUG && console.warn(element.innerHTML);
      const label: ElkLabel = labels[i];
      const size: DOMRect = element.getBoundingClientRect();

      label.width = size.width;
      label.height = size.height;

      i++;
    }
  }
}

export class ELKTextSizerView extends DOMWidgetView {
  static view_name = 'ELKTextSizerView';
  model: ELKTextSizerModel;
  async render() {}
}

/**
 * SVG Required Namespaced Element
 */
function createSVGElement(tag: string): SVGElement {
  return document.createElementNS('http://www.w3.org/2000/svg', tag);
}

function get_labels(el: any): ElkLabel[] {
  let labels: ElkLabel[] = [];
  if (el?.labels) {
    for (let label of el.labels as ElkLabel[]) {
      // size only those labels without a width or a height set
      if (!label?.properties?.shape?.width || !label?.properties?.shape?.height) {
        labels.push(label);
      }
    }
  }
  for (let child of el?.ports || []) {
    labels.push(...get_labels(child));
  }
  for (let child of el?.children || []) {
    labels.push(...get_labels(child));
  }
  for (let edge of el?.edges || []) {
    labels.push(...get_labels(edge));
  }
  for (let label of el?.labels || []) {
    labels.push(...get_labels(label));
  }

  return labels;
}
