/*
 * Copyright The NOMAD Authors.
 *
 * This file is part of NOMAD. See https://nomad-lab.eu for further info.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
import React, { useState, useLayoutEffect, useMemo, useRef, useCallback } from 'react'
import PropTypes from 'prop-types'
import { cloneDeep } from 'lodash'
import { useHistory } from 'react-router-dom'
import { makeStyles } from '@material-ui/core/styles'
import {
  Typography,
  Box,
  Tooltip
} from '@material-ui/core'
import {
  Fullscreen,
  FullscreenExit,
  CameraAlt,
  Replay,
  ViewList,
  Warning
} from '@material-ui/icons'
import Floatable from './Floatable'
import Placeholder from '../visualization/Placeholder'
import NoData from './NoData'
import Actions from '../Actions'
import Plotly from 'plotly.js-cartesian-dist-min'
import clsx from 'clsx'
import { mergeObjects } from '../../utils'

export default function Plot({
  data,
  layout,
  config,
  floatTitle,
  metaInfoLink,
  capture,
  aspectRatio,
  fixedMargins,
  className,
  classes,
  placeHolderStyle,
  noDataStyle,
  warning,
  onRelayout,
  onRedraw,
  onRelayouting,
  onHover,
  onReset,
  layoutSubject
}) {
  // States
  const [float, setFloat] = useState(false)
  const firstRender = useRef(true)
  const [canvasNode, setCanvasNode] = useState()
  const [margins, setMargins] = useState()
  const attach = useRef()
  const [loading, setLoading] = useState(true)
  const history = useHistory()

  const captureSettings = useMemo(() => {
    let defaultCapture = {
      format: 'png',
      width: 1024,
      height: 960 / aspectRatio,
      filename: 'plot'
    }
    let settings = mergeObjects(capture, defaultCapture)
    return settings
  }, [capture, aspectRatio])

  // Styles
  const useStyles = makeStyles((theme) => {
    return {
      footer: {
        paddingRight: theme.spacing(1),
        display: 'flex',
        flexDirection: 'row',
        zIndex: 1
      },
      root: {
      },
      placeHolder: {
        left: 0,
        right: 0,
        position: 'absolute'
      },
      floatable: {
        visibility: loading ? 'hidden' : 'visible'
      },
      spacer: {
        flex: 1
      },
      warning: {
        color: theme.palette.warning.main,
        position: 'absolute',
        zIndex: 1,
        left: '2px',
        top: '20px'
      },
      iconButton: {
        backgroundColor: 'white',
        marginLeft: theme.spacing(1)
      }
    }
  })
  const styles = useStyles({classes: classes})

  // Set the final layout
  const finalLayout = useMemo(() => {
    let defaultLayout = {
      dragmode: 'pan',
      hovermode: false,
      showlegend: false,
      autosize: true,
      // There is extra space reserved for the top and bottom margins so that
      // automargin does not make the plot jump around too much.
      margin: {
        l: 30,
        r: 20,
        t: 20,
        b: 50
      },
      title: {
        font: {
          family: 'Titillium Web,sans-serif'
        }
      },
      legend: {
        bgcolor: 'rgba(255, 255, 255, 0.9)',
        font: {
          family: 'Titillium Web,sans-serif',
          size: 14
        }
      },
      xaxis: {
        automargin: false,
        autorange: true,
        linecolor: '#333',
        linewidth: 1,
        mirror: true,
        ticks: 'outside',
        showline: true,
        fixedrange: true,
        title: {
          standoff: 10,
          font: {
            family: 'Titillium Web,sans-serif',
            size: 16,
            color: '#333'
          },
          tickfont: {
            family: 'Titillium Web,sans-serif',
            size: 14,
            color: '#333'
          }
        }
      },
      yaxis: {
        automargin: true,
        autorange: true,
        linecolor: '#333',
        linewidth: 1,
        mirror: true,
        ticks: 'outside',
        showline: true,
        title: {
          standoff: 10,
          font: {
            family: 'Titillium Web,sans-serif',
            size: 16,
            color: '#333'
          }
        },
        tickfont: {
          family: 'Titillium Web,sans-serif',
          size: 14,
          color: '#333'
        }
      },
      yaxis2: {
        automargin: true,
        autorange: true,
        linecolor: '#333',
        linewidth: 1,
        mirror: true,
        ticks: 'outside',
        showline: true,
        title: {
          standoff: 10,
          font: {
            family: 'Titillium Web,sans-serif',
            size: 16,
            color: '#333'
          }
        },
        tickfont: {
          family: 'Titillium Web,sans-serif',
          size: 14,
          color: '#333'
        }
      }
    }
    const finalLayoutResult = mergeObjects(layout, defaultLayout)
    return finalLayoutResult
  }, [layout])

  // Save the initial layout as reset
  const finalResetLayout = useMemo(() => {
    const resLayout = cloneDeep(finalLayout)
    if (margins) {
      resLayout.yaxis.automargin = false
      resLayout.yaxis2.automargin = false
      resLayout.xaxis.automargin = false
      resLayout.margin.l = margins.l
      resLayout.margin.t = margins.t
      resLayout.margin.r = margins.r
    }
    return resLayout
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [margins])

  // Set the final config
  const finalConfig = useMemo(() => {
    let defaultConfig = {
      scrollZoom: true,
      displayModeBar: false,
      showTips: false
    }
    return mergeObjects(config, defaultConfig)
  }, [config])

  // This callback redraws the plot whenever the canvas element changes. In
  // order to properly detect changes in a reference, a reference callback is
  // used. This is the recommended way to monitor reference changes as a simple
  // useRef is not guaranteed to update:
  // https://reactjs.org/docs/hooks-faq.html#how-can-i-measure-a-dom-node
  const canvasRef = useCallback(node => {
    if (node) {
      if (!firstRender.current) {
        attach.current = true
        // We use a dummy state to request a redraw on the new canvas
        setCanvasNode(node)
      }
      // We add a NATIVE wheel event handler that prevents the wheel events sent
      // by Plotly from bubbling up. Notice that the SyntheticEvents added by
      // React cannot be used, since they do not play well with the original
      // native events created by Plotly (in particular: SyntheticEvents are all
      // passive, so calling preventDefault on them will cause problems on
      // browsers that support passive events.)
      node.addEventListener('wheel', (e) => {
        e.preventDefault()
        e.stopPropagation()
      })
    }
    canvasRef.current = node
  }, [])

  // Update plots when data, config or rendering canvas is updated.
  // useLayoutEffect is used so that React rendering and Plotly rendering are
  // synced.
  useLayoutEffect(() => {
    if (!data) {
      return
    }
    if (firstRender.current) {
      Plotly.newPlot(canvasRef.current, data, finalLayout, finalConfig)
      attach.current = true
      firstRender.current = false

      // Subscribe to the layout change publisher if one is given
      if (layoutSubject) {
        layoutSubject.subscribe(layout => {
          let oldLayout = canvasRef.current.layout
          // The updates are throttled by using requestAnimationFrame: there is
          // no sense in trying to update beyond what the browser can render
          window.requestAnimationFrame(() => { Plotly.relayout(canvasRef.current, mergeObjects(layout, oldLayout)) })
        })
      }
      setLoading(false)
    } else {
      Plotly.react(canvasRef.current, data, finalLayout, finalConfig)
    }
    // Upon first render or changing the plot DOM element the events are (re-)attached.
    if (attach.current === true) {
      if (onRelayouting) {
        canvasRef.current.on('plotly_relayouting', onRelayouting)
      }
      if (onRedraw) {
        canvasRef.current.on('plotly_redraw', onRedraw)
      }
      if (onRelayout) {
        canvasRef.current.on('plotly_relayout', onRelayout)
      }
      if (onHover) {
        canvasRef.current.on('plotly_hover', onHover)
      }

      attach.current = false
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutSubject, canvasNode, firstRender, data, finalConfig])

  // Captures the first margin value from the plot and performs
  useLayoutEffect(() => {
    if (fixedMargins && canvasRef.current) {
      try {
        // Get the element which explicitly stores the computed margin and
        // perform a relayout with these values.
        const group = canvasRef.current.children[0].children[0].children[0].children[2].children[0].children[0]
        const currentLayout = canvasRef.current.layout
        currentLayout.yaxis.automargin = false
        currentLayout.yaxis2.automargin = false
        currentLayout.xaxis.automargin = false
        currentLayout.margin.l = parseInt(group.getAttribute('x'))
        currentLayout.margin.t = parseInt(group.getAttribute('y'))
        const totalWidth = canvasRef.current.clientWidth
        const plotAreaWidth = parseInt(group.getAttribute('width'))
        currentLayout.margin.r = totalWidth - plotAreaWidth - currentLayout.margin.l
        Plotly.relayout(canvasRef.current, currentLayout)

        // Save the margins so that they can also be updated on the reset config
        setMargins({l: currentLayout.margin.l, t: currentLayout.margin.t, r: currentLayout.margin.r})
      } catch (e) {
        console.log('Could not determine the margin values.')
      }
    }
  }, [canvasRef, data, fixedMargins])

  // For resetting the view.
  const handleReset = useCallback(() => {
    if (canvasRef?.current && finalResetLayout) {
      Plotly.relayout(canvasRef.current, mergeObjects(finalResetLayout, canvasRef.current.layout))
      if (onReset) {
        onReset()
      }
    }
  }, [canvasRef, finalResetLayout, onReset])

  // Handles plot capturing
  const handleCapture = useCallback(() => {
    Plotly.downloadImage(canvasRef.current, captureSettings)
  }, [canvasRef, captureSettings])

  // List of actionable buttons for the plot
  const actions = [
    {tooltip: 'Reset view', onClick: handleReset, content: <Replay/>},
    {tooltip: 'Toggle fullscreen', onClick: () => setFloat(!float), content: float ? <FullscreenExit/> : <Fullscreen/>},
    {tooltip: 'Capture image', onClick: handleCapture, content: <CameraAlt/>}
  ]
  if (metaInfoLink) {
    actions.push({tooltip: 'View data in the archive', onClick: () => { history.push(metaInfoLink) }, content: <ViewList/>})
  }

  // If data is set explicitly to False, we show the NoData component.
  if (data === false) {
    return <Box className={clsx(className, styles.root)} position='relative' width='100%'>
      <NoData aspectRatio={aspectRatio} classes={{placeholder: noDataStyle}}/>
    </Box>
  }
  // Even if the plots are still loading, all the html elements need to be
  // placed in the DOM. During loading, they are placed underneath the
  // placeholder with visibility=hidden. This way Plotly still has access to
  // these HTML nodes and their sizes when the plots are loading.
  return <Box className={clsx(className, styles.root)} position='relative' width='100%'>
    {loading && <Placeholder className={styles.placeHolder} classes={{placeholder: placeHolderStyle}} variant="rect" aspectRatio={aspectRatio}></Placeholder>}
    <Floatable className={styles.floatable} float={float} onFloat={() => setFloat(!float)} aspectRatio={aspectRatio}>
      {float && <Typography variant="h6">{floatTitle}</Typography>}
      <div ref={canvasRef} style={{width: '100%', height: '100%', position: 'relative'}}>
        {warning && <Tooltip title={warning}>
          <Warning className={styles.warning}></Warning>
        </Tooltip>}
      </div>
      <div className={styles.footer}>
        <Actions actions={actions}></Actions>
      </div>
    </Floatable>
  </Box>
}

Plot.propTypes = {
  data: PropTypes.any, // Plotly.js data object: Set to null to show Placeholder, set to false to show NoData.
  layout: PropTypes.object, // Plotly.js layout object
  config: PropTypes.object, // Plotly.js config object
  capture: PropTypes.object, // Capture settings
  aspectRatio: PropTypes.number, // Fixed aspect ratio for the viewer canvas
  fixedMargins: PropTypes.bool, // Whether to automatically update margins beyond the first render.
  className: PropTypes.string,
  classes: PropTypes.object,
  placeHolderStyle: PropTypes.string, // The CSS class to apply for the Placeholder component.
  noDataStyle: PropTypes.string, // The CSS class to apply for the NoData component.
  floatTitle: PropTypes.string, // The title of the plot shown in floating mode
  metaInfoLink: PropTypes.string, // A link to the metainfo definition
  warning: PropTypes.string, // Optional message displayed under a warning icon on the top-left corner of the element.
  onRelayout: PropTypes.func,
  onRedraw: PropTypes.func,
  onRelayouting: PropTypes.func,
  onHover: PropTypes.func,
  onReset: PropTypes.func,
  /**
   * A RxJS Subject for efficient, non-persistent, layout changes that bypass
   * rendering of the component. Should send messages that contain the new
   * layout object.
  */
  layoutSubject: PropTypes.any
}
Plot.defaultProps = {
  aspectRatio: 9 / 16,
  floatTitle: '',
  fixedMargins: true
}