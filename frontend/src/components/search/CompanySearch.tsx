import { useNavigate } from 'react-router-dom'
import { TickerAutocomplete } from './TickerAutocomplete'

export function CompanySearch() {
  const navigate = useNavigate()

  return (
    <TickerAutocomplete
      onSelect={(result) => navigate(`/research/${result.ticker}`)}
      placeholder="Search ticker or company..."
      showIcon={true}
      inputClassName="py-1.5"
      clearOnSelect={true}
      allowRawTicker={true}
    />
  )
}
