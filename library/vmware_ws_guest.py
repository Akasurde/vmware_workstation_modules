#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This module is also sponsored by E.T.A.I. (www.etai.fr)
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {'metadata_version': '1.0',
                    'status': ['preview'],
                    'supported_by': 'community'}


DOCUMENTATION = '''
---
module: vmware_ws_guest
short_description: Manages virtual machines in vmware workstation
description:
    - Create new virtual machines (from templates or OVAs)
    - Power on/power off/restart a virtual machine
    - Modify, rename or remove a virtual machine
version_added: 2.4
author:
    - James Tanner (@jctanner) <tanner.jc@gmail.com>
notes:
    - Tested on vmware workstation 12.5
requirements:
    - "python >= 2.6"
    - PyVmomi
options:
   state:
        description:
            - What state should the virtual machine be in?
            - If C(state) is set to C(present) and VM exists, ensure the VM configuration conforms to task arguments
        required: True
        choices: ['present', 'absent', 'poweredon', 'poweredoff', 'restarted', 'suspended', 'shutdownguest', 'rebootguest']
   name:
        description:
            - Name of the VM to work with
        required: True
   template:
        description:
            - Template used to create VM.
            - If this value is not set, VM is created without using a template.
            - If the VM exists already this setting will be ignored.
   ova:
        description:
            - OVA file to import.
            - If the VM exists already this setting will be ignored.
'''

EXAMPLES = '''
'''

RETURN = """
"""

import os
import shutil
import time

# import module snippets
from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.pycompat24 import get_exception
from ansible.module_utils.six import iteritems

from ansible.module_utils.vmware_workstation import VMwareWorkstationHelper


def main():

    state_options = [
        'present',
        'absent'
    ]

    power_options = [
        'poweredon',
        'poweredoff',
        'restarted',
        'suspended',
        'shutdownguest',
        'rebootguest'
    ]

    create_options = [
        'poweredon',
        'poweredoff',
        'present',
        'restarted',
        'suspended'
    ]

    module = AnsibleModule(
        argument_spec=dict(
            state=dict(
                required=False,
                choices=state_options + power_options,
                default='present'),
            template_src=dict(type='str', aliases=['template']),
            ova=dict(type='str'),
            name=dict(required=True, type='str'),
        ),
        supports_check_mode=True,
    )

    vmwh = VMwareWorkstationHelper(module)

    result = {
        'failed': False,
        'changed': False,
        'operations': []
    }

    vm = vmwh.get_workstation_vm_by_name(
        module.params['name'],
        filter_unknown=False
    )

    if vm:
        # VM already exists

        if module.params['state'] == 'absent':

            # has to be poweredoff first
            (cmd, rc, so, se) = vmwh.stop_vm(vm['config'])
            result['operations'].append(cmd)
            result['rc_stop'] = rc
            result['so_stop'] = so
            result['se_stop'] = se

            # destroy it
            (cmd, rc, so, se) = vmwh.delete_vm(vm['config'])
            result['operations'].append(cmd)

            result['rc_delete'] = rc
            result['so_delete'] = so
            result['se_delete'] = se
            if rc != 0:
                module.fail_json(msg="Destroying the VM failed", meta=result)

            time.sleep(5)

            vmxdir = vm['config']
            vmxdir = os.path.dirname(vmxdir)
            if os.path.isdir(vmxdir):
                shutil.rmtree(vmxdir)

            result['changed'] = True

        elif module.params['state'] == 'present':

            result['instances'] = []
            result['instances'].append(vm)

        elif module.params['state'] in power_options:

            if module.params['state'] == 'poweredon':

                if not os.path.isfile(vm['config']):
                    module.fail_json(msg="VMX(%s) does not exist, poweron will fail" % vm['config'], meta=result)

                (cmd, rc, so, se) = vmwh.start_vm(vm['config'])
                result['operations'].append(cmd)
                result['rc_poweron'] = rc
                result['so_poweron'] = so
                result['se_poweron'] = se
                if rc != 0:
                    module.fail_json(msg="Powering on the VM failed", meta=result)

                result['changed'] = True

            new_vm = vmwh.get_workstation_vm_by_name(module.params['name'])
            result['instances'] = []
            result['instances'].append(new_vm)

        else:
            # This should not happen
            assert False

    else:
        # VM doesn't exist

        if module.params['state'] in create_options:

            if module.params['template_src']:

                # Get template path
                template = vmwh.get_workstation_vm_by_name(
                    module.params['template_src'],
                    filter_unknown=False
                )
                if not template:
                    module.fail_json(msg='template %s was not found' % module.params['template_src'])
                template_vmxpath = template['config']

                # Create path for new vmx
                vmxdir = os.path.expanduser('~/vmware')
                vmxdir = os.path.join(vmxdir, module.params['name'])

                if not os.path.isdir(vmxdir):
                    os.makedirs(vmxdir)
                result['vmxdir'] = vmxdir

                vmxpath = os.path.join(vmxdir, '%s.vmx' % module.params['name'])
                result['vmxpath'] = vmxpath

                # Clone it ...
                (cmd, rc, so, se) = vmwh.clone_vm(module.params['name'], vmxpath, template_vmxpath)
                result['operations'].append(cmd)
                result['rc'] = rc
                result['so'] = so
                result['se'] = se

                time.sleep(5)

                if rc != 0 or not os.path.isfile(vmxpath):
                    module.fail_json(msg="Cloning the VM failed", meta=result)

            elif module.params['ova']:

                ova_name = vmwh.get_ova_display_name(module.params['ova'])
                ova_vm = vmwh.get_workstation_vm_by_name(
                    ova_name,
                    filter_unknown=False
                )

                if ova_vm:
                    result['changed'] = False
                else:
                    (cmd, rc, so, se) = vmwh.import_ova(module.params['ova'], accept_eula=True)
                    result['operations'].append(cmd)
                    result['rc_import'] = rc
                    result['so_import'] = so
                    result['se_import'] = se

                    time.sleep(5)

                    if rc != 0:
                        module.fail_json(msg="Importing the OVA failed", meta=result)

            if module.params['state'] == 'poweredon':

                (cmd, rc, so, se) = vmwh.start_vm(vmxpath)
                result['operations'].append(cmd)
                result['rc_poweron'] = rc
                result['so_poweron'] = so
                result['se_poweron'] = se
                if rc != 0:
                    module.fail_json(msg="Powering on the VM failed", meta=result)

            time.sleep(60)

            new_vm = vmwh.get_workstation_vm_by_name(module.params['name'])
            result['instances'] = []
            result['instances'].append(new_vm)

    if 'failed' not in result:
        result['failed'] = False

    if result['failed']:
        module.fail_json(**result)
    else:
        module.exit_json(**result)


if __name__ == '__main__':
    main()
