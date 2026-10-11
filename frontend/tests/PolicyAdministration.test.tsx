import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import PolicyAdministration from '../src/PolicyAdministration'
const config={role_permissions:{administrator:['entity.manage'],inventory_analyst:['forecast.manage'],procurement_manager:['action.decide'],auditor:['audit.read']},entity_clearance:{suppliers:1,inventory:1},operation_clearance:{'inventory.change':1,'forecast.modify':1},approval_quantity_threshold:1000000000,approval_risk_threshold:100,rules:[]}
const revision={id:1,configuration:config,status:'published',base_generation:0,digest:'digest',created_by:null,created_at:'2026-10-11T10:00:00Z',reason:'Initial security policy',published_by:null,published_at:'2026-10-11T10:00:00Z'}
const overview={generation:1,active_revision_id:1,configuration:config,permission_ceiling:config.role_permissions,clearance_levels:{administrator:4,inventory_analyst:2,procurement_manager:3,auditor:1},revisions:[revision],users:[{id:1,display_name:'Admin',role:'administrator'},{id:2,display_name:'Analyst',role:'inventory_analyst'}]}
afterEach(()=>{cleanup();vi.restoreAllMocks()})
function mockFetch(){return vi.fn(async(url:string,init?:RequestInit)=>({ok:true,json:async()=>init?.method==='POST'?(url.endsWith('/drafts')?{...revision,id:2,status:'draft',base_generation:1,configuration:JSON.parse(String(init.body)).configuration}:{generation:2,active_revision_id:2}):overview}))}
function mount(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><PolicyAdministration token="token"/></QueryClientProvider>)}
it('saves a draft and requires separate review and publication confirmation',async()=>{
 const fetch=mockFetch();vi.stubGlobal('fetch',fetch);mount();fireEvent.click(await screen.findByRole('button',{name:'Create policy draft'}))
 fireEvent.click(screen.getByLabelText('forecast · manage'));fireEvent.change(screen.getByLabelText('Draft reason'),{target:{value:'Restrict forecast changes'}});fireEvent.click(screen.getByRole('button',{name:'Save draft for review'}))
 expect(await screen.findByRole('region',{name:'Policy publication review'})).toHaveTextContent('No permissions');expect(fetch.mock.calls.some(([url])=>url.endsWith('/publish'))).toBe(false)
 fireEvent.change(screen.getByLabelText('Publication reason'),{target:{value:'Reviewed impact on analyst'}});fireEvent.click(screen.getByRole('button',{name:'Confirm and publish policy'}))
 expect(await screen.findByText('Policy published. Backend enforcement now uses this revision.')).toBeInTheDocument()
 const published=fetch.mock.calls.find(([url])=>url.endsWith('/publish'))!;expect(JSON.parse(String(published[1]?.body))).toEqual({expected_generation:1,reason:'Reviewed impact on analyst'})
})
it('protects administrator permissions and edits operation rules',async()=>{
 vi.stubGlobal('fetch',mockFetch());mount();fireEvent.click(await screen.findByRole('button',{name:'Create policy draft'}));expect(screen.getByLabelText('entity · manage')).toBeDisabled()
 fireEvent.click(screen.getByRole('button',{name:'Add operation rule'}));fireEvent.change(screen.getByLabelText('Maximum absolute quantity change (optional)'),{target:{value:'25'}});fireEvent.change(screen.getByLabelText('Rule identifier'),{target:{value:'sensitive-stock'}})
 fireEvent.change(screen.getByLabelText('Draft reason'),{target:{value:'Limit adjustments'}});fireEvent.click(screen.getByRole('button',{name:'Save draft for review'}));expect(await screen.findByRole('region',{name:'Policy publication review'})).toHaveTextContent('sensitive-stock')
})
it('shows access errors and retries loading',async()=>{
 const fetch=vi.fn().mockResolvedValueOnce({ok:false,json:async()=>({detail:'Only administrators may configure policies'})}).mockResolvedValue({ok:true,json:async()=>overview});vi.stubGlobal('fetch',fetch);mount()
 expect(await screen.findByRole('alert')).toHaveTextContent('Only administrators');fireEvent.click(screen.getByRole('button',{name:'Retry policy load'}));expect(await screen.findByText('Published revision 1')).toBeInTheDocument()
})
it('shows validation errors without publishing a draft',async()=>{
 const fetch=mockFetch();vi.stubGlobal('fetch',vi.fn((url:string,init?:RequestInit)=>url.endsWith('/drafts')?Promise.resolve({ok:false,json:async()=>({detail:'Rule identifiers must be unique'})}):fetch(url,init)));mount()
 fireEvent.click(await screen.findByRole('button',{name:'Create policy draft'}));fireEvent.change(screen.getByLabelText('Draft reason'),{target:{value:'Review controls'}});fireEvent.click(screen.getByRole('button',{name:'Save draft for review'}))
 expect(await screen.findByRole('alert')).toHaveTextContent('Rule identifiers must be unique');expect(screen.queryByRole('button',{name:'Confirm and publish policy'})).toBeNull()
})
