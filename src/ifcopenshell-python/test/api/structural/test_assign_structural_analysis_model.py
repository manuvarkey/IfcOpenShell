# IfcOpenShell - IFC toolkit and geometry engine
# Copyright (C) 2021 Dion Moult <dion@thinkmoult.com>
#
# This file is part of IfcOpenShell.
#
# IfcOpenShell is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# IfcOpenShell is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with IfcOpenShell.  If not, see <http://www.gnu.org/licenses/>.

import test.bootstrap
import ifcopenshell.api.root
import ifcopenshell.api.structural


class TestAssignStructuralAnalysisModel(test.bootstrap.IFC4):
    def test_assigning_a_structural_analysis_model(self):
        subject = ifcopenshell.api.structural.add_structural_analysis_model(self.file)
        product = ifcopenshell.api.root.create_entity(
            self.file, ifc_class="IfcStructuralMember", predefined_type=None, name=None
        )
        rel = ifcopenshell.api.structural.assign_structural_analysis_model(
            self.file,
            products=[product],
            structural_analysis_model=subject,
        )
        assert rel
        assert rel.is_a("IfcRelAssignsToGroup")
        assert rel.RelatingGroup == subject
        assert rel.RelatedObjects == (product,)


class TestAssignStructuralAnalysisModelIFC2X3(test.bootstrap.IFC2X3, TestAssignStructuralAnalysisModel):
    pass
