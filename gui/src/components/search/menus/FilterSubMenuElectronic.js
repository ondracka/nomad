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
import React, { useContext } from 'react'
import PropTypes from 'prop-types'
import { FilterSubMenu, filterMenuContext } from './FilterMenu'
import { InputGrid, InputGridItem } from '../input/InputGrid'
import InputSection from '../input/InputSection'
import InputSlider from '../input/InputSlider'
import InputField from '../input/InputField'
import { Quantity, useUnits } from '../../../units'

const step = new Quantity(0.1, 'electron_volt')

const FilterSubMenuElectronic = React.memo(({
  value,
  ...rest
}) => {
  const units = useUnits()
  const {selected} = useContext(filterMenuContext)
  const visible = value === selected

  return <FilterSubMenu value={value} {...rest}>
    <InputGrid>
      <InputGridItem xs={12}>
        <InputField
          quantity="electronic_properties"
          visible={visible}
          disableSearch
        />
      </InputGridItem>
      <InputGridItem xs={12}>
        <InputSection
          section="results.properties.electronic.band_structure_electronic.band_gap"
          visible={visible}
        >
          <InputField
            quantity="results.properties.electronic.band_structure_electronic.band_gap.type"
            visible={visible}
            disableSearch
          />
          <InputSlider
            quantity="results.properties.electronic.band_structure_electronic.band_gap.value"
            units={units}
            step={step}
            visible={visible}
          />
        </InputSection>
      </InputGridItem>
      <InputGridItem xs={12}>
        <InputSection
          section="results.properties.electronic.band_structure_electronic"
          visible={visible}
        >
          <InputField
            quantity="results.properties.electronic.band_structure_electronic.spin_polarized"
            visible={visible}
            disableSearch
          />
        </InputSection>
      </InputGridItem>
      <InputGridItem xs={12}>
        <InputSection
          section="results.properties.electronic.dos_electronic"
          visible={visible}
        >
          <InputField
            quantity="results.properties.electronic.dos_electronic.spin_polarized"
            visible={visible}
            disableSearch
          />
        </InputSection>
      </InputGridItem>
    </InputGrid>
  </FilterSubMenu>
})
FilterSubMenuElectronic.propTypes = {
  value: PropTypes.string
}

export default FilterSubMenuElectronic