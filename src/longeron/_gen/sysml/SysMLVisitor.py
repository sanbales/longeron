# Generated from grammars/SysML.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .SysMLParser import SysMLParser
else:
    from SysMLParser import SysMLParser

# This class defines a complete generic visitor for a parse tree produced by SysMLParser.

class SysMLVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by SysMLParser#definedByToken.
    def visitDefinedByToken(self, ctx:SysMLParser.DefinedByTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#specializesToken.
    def visitSpecializesToken(self, ctx:SysMLParser.SpecializesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subsetsToken.
    def visitSubsetsToken(self, ctx:SysMLParser.SubsetsTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#referencesToken.
    def visitReferencesToken(self, ctx:SysMLParser.ReferencesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#crossesToken.
    def visitCrossesToken(self, ctx:SysMLParser.CrossesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#redefinesToken.
    def visitRedefinesToken(self, ctx:SysMLParser.RedefinesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#qualifiedName.
    def visitQualifiedName(self, ctx:SysMLParser.QualifiedNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#identification.
    def visitIdentification(self, ctx:SysMLParser.IdentificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#relationshipBody.
    def visitRelationshipBody(self, ctx:SysMLParser.RelationshipBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#dependency.
    def visitDependency(self, ctx:SysMLParser.DependencyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#dependencyDeclaration.
    def visitDependencyDeclaration(self, ctx:SysMLParser.DependencyDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#annotation.
    def visitAnnotation(self, ctx:SysMLParser.AnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedAnnotation.
    def visitOwnedAnnotation(self, ctx:SysMLParser.OwnedAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#annotatingMember.
    def visitAnnotatingMember(self, ctx:SysMLParser.AnnotatingMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#annotatingElement.
    def visitAnnotatingElement(self, ctx:SysMLParser.AnnotatingElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#comment.
    def visitComment(self, ctx:SysMLParser.CommentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#documentation.
    def visitDocumentation(self, ctx:SysMLParser.DocumentationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#textualRepresentation.
    def visitTextualRepresentation(self, ctx:SysMLParser.TextualRepresentationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#rootNamespace.
    def visitRootNamespace(self, ctx:SysMLParser.RootNamespaceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#package.
    def visitPackage(self, ctx:SysMLParser.PackageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#libraryPackage.
    def visitLibraryPackage(self, ctx:SysMLParser.LibraryPackageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#packageDeclaration.
    def visitPackageDeclaration(self, ctx:SysMLParser.PackageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#packageBody.
    def visitPackageBody(self, ctx:SysMLParser.PackageBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#packageBodyElement.
    def visitPackageBodyElement(self, ctx:SysMLParser.PackageBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#visibility.
    def visitVisibility(self, ctx:SysMLParser.VisibilityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#memberPrefix.
    def visitMemberPrefix(self, ctx:SysMLParser.MemberPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#packageMember.
    def visitPackageMember(self, ctx:SysMLParser.PackageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#elementFilterMember.
    def visitElementFilterMember(self, ctx:SysMLParser.ElementFilterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#aliasMember.
    def visitAliasMember(self, ctx:SysMLParser.AliasMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#import_.
    def visitImport_(self, ctx:SysMLParser.Import_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#importDeclaration.
    def visitImportDeclaration(self, ctx:SysMLParser.ImportDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#membershipImport.
    def visitMembershipImport(self, ctx:SysMLParser.MembershipImportContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#namespaceImport.
    def visitNamespaceImport(self, ctx:SysMLParser.NamespaceImportContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#filterPackage.
    def visitFilterPackage(self, ctx:SysMLParser.FilterPackageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#filterPackageMember.
    def visitFilterPackageMember(self, ctx:SysMLParser.FilterPackageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#visibilityIndicator.
    def visitVisibilityIndicator(self, ctx:SysMLParser.VisibilityIndicatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionElement.
    def visitDefinitionElement(self, ctx:SysMLParser.DefinitionElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usageElement.
    def visitUsageElement(self, ctx:SysMLParser.UsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#basicDefinitionPrefix.
    def visitBasicDefinitionPrefix(self, ctx:SysMLParser.BasicDefinitionPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionExtensionKeyword.
    def visitDefinitionExtensionKeyword(self, ctx:SysMLParser.DefinitionExtensionKeywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionPrefix.
    def visitDefinitionPrefix(self, ctx:SysMLParser.DefinitionPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definition.
    def visitDefinition(self, ctx:SysMLParser.DefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionDeclaration.
    def visitDefinitionDeclaration(self, ctx:SysMLParser.DefinitionDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionBody.
    def visitDefinitionBody(self, ctx:SysMLParser.DefinitionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionBodyItem.
    def visitDefinitionBodyItem(self, ctx:SysMLParser.DefinitionBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#definitionMember.
    def visitDefinitionMember(self, ctx:SysMLParser.DefinitionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#variantUsageMember.
    def visitVariantUsageMember(self, ctx:SysMLParser.VariantUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonOccurrenceUsageMember.
    def visitNonOccurrenceUsageMember(self, ctx:SysMLParser.NonOccurrenceUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceUsageMember.
    def visitOccurrenceUsageMember(self, ctx:SysMLParser.OccurrenceUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#structureUsageMember.
    def visitStructureUsageMember(self, ctx:SysMLParser.StructureUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#behaviorUsageMember.
    def visitBehaviorUsageMember(self, ctx:SysMLParser.BehaviorUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureDirection.
    def visitFeatureDirection(self, ctx:SysMLParser.FeatureDirectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#refPrefix.
    def visitRefPrefix(self, ctx:SysMLParser.RefPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#basicUsagePrefix.
    def visitBasicUsagePrefix(self, ctx:SysMLParser.BasicUsagePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#endUsagePrefix.
    def visitEndUsagePrefix(self, ctx:SysMLParser.EndUsagePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedCrossFeatureMember.
    def visitOwnedCrossFeatureMember(self, ctx:SysMLParser.OwnedCrossFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedCrossFeature.
    def visitOwnedCrossFeature(self, ctx:SysMLParser.OwnedCrossFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usageExtensionKeyword.
    def visitUsageExtensionKeyword(self, ctx:SysMLParser.UsageExtensionKeywordContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#unextendedUsagePrefix.
    def visitUnextendedUsagePrefix(self, ctx:SysMLParser.UnextendedUsagePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usagePrefix.
    def visitUsagePrefix(self, ctx:SysMLParser.UsagePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usage.
    def visitUsage(self, ctx:SysMLParser.UsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usageDeclaration.
    def visitUsageDeclaration(self, ctx:SysMLParser.UsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usageCompletion.
    def visitUsageCompletion(self, ctx:SysMLParser.UsageCompletionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#usageBody.
    def visitUsageBody(self, ctx:SysMLParser.UsageBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#valuePart.
    def visitValuePart(self, ctx:SysMLParser.ValuePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureValue.
    def visitFeatureValue(self, ctx:SysMLParser.FeatureValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#defaultReferenceUsage.
    def visitDefaultReferenceUsage(self, ctx:SysMLParser.DefaultReferenceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#referenceUsage.
    def visitReferenceUsage(self, ctx:SysMLParser.ReferenceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#variantReference.
    def visitVariantReference(self, ctx:SysMLParser.VariantReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonOccurrenceUsageElement.
    def visitNonOccurrenceUsageElement(self, ctx:SysMLParser.NonOccurrenceUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceUsageElement.
    def visitOccurrenceUsageElement(self, ctx:SysMLParser.OccurrenceUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#structureUsageElement.
    def visitStructureUsageElement(self, ctx:SysMLParser.StructureUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#behaviorUsageElement.
    def visitBehaviorUsageElement(self, ctx:SysMLParser.BehaviorUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#variantUsageElement.
    def visitVariantUsageElement(self, ctx:SysMLParser.VariantUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subclassificationPart.
    def visitSubclassificationPart(self, ctx:SysMLParser.SubclassificationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedSubclassification.
    def visitOwnedSubclassification(self, ctx:SysMLParser.OwnedSubclassificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureSpecializationPart.
    def visitFeatureSpecializationPart(self, ctx:SysMLParser.FeatureSpecializationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureSpecialization.
    def visitFeatureSpecialization(self, ctx:SysMLParser.FeatureSpecializationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#typings.
    def visitTypings(self, ctx:SysMLParser.TypingsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#typedBy.
    def visitTypedBy(self, ctx:SysMLParser.TypedByContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureTyping.
    def visitFeatureTyping(self, ctx:SysMLParser.FeatureTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedFeatureTyping.
    def visitOwnedFeatureTyping(self, ctx:SysMLParser.OwnedFeatureTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subsettings.
    def visitSubsettings(self, ctx:SysMLParser.SubsettingsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subsets.
    def visitSubsets(self, ctx:SysMLParser.SubsetsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedSubsetting.
    def visitOwnedSubsetting(self, ctx:SysMLParser.OwnedSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#references.
    def visitReferences(self, ctx:SysMLParser.ReferencesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedReferenceSubsetting.
    def visitOwnedReferenceSubsetting(self, ctx:SysMLParser.OwnedReferenceSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#crosses.
    def visitCrosses(self, ctx:SysMLParser.CrossesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedCrossSubsetting.
    def visitOwnedCrossSubsetting(self, ctx:SysMLParser.OwnedCrossSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#redefinitions.
    def visitRedefinitions(self, ctx:SysMLParser.RedefinitionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#redefines.
    def visitRedefines(self, ctx:SysMLParser.RedefinesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedRedefinition.
    def visitOwnedRedefinition(self, ctx:SysMLParser.OwnedRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedFeatureChain.
    def visitOwnedFeatureChain(self, ctx:SysMLParser.OwnedFeatureChainContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedFeatureChaining.
    def visitOwnedFeatureChaining(self, ctx:SysMLParser.OwnedFeatureChainingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#multiplicityPart.
    def visitMultiplicityPart(self, ctx:SysMLParser.MultiplicityPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedMultiplicity.
    def visitOwnedMultiplicity(self, ctx:SysMLParser.OwnedMultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#multiplicityRange.
    def visitMultiplicityRange(self, ctx:SysMLParser.MultiplicityRangeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#multiplicityExpressionMember.
    def visitMultiplicityExpressionMember(self, ctx:SysMLParser.MultiplicityExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#attributeDefinition.
    def visitAttributeDefinition(self, ctx:SysMLParser.AttributeDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#attributeUsage.
    def visitAttributeUsage(self, ctx:SysMLParser.AttributeUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#enumerationDefinition.
    def visitEnumerationDefinition(self, ctx:SysMLParser.EnumerationDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#enumerationBody.
    def visitEnumerationBody(self, ctx:SysMLParser.EnumerationBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#enumerationUsageMember.
    def visitEnumerationUsageMember(self, ctx:SysMLParser.EnumerationUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#enumeratedValue.
    def visitEnumeratedValue(self, ctx:SysMLParser.EnumeratedValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#enumerationUsage.
    def visitEnumerationUsage(self, ctx:SysMLParser.EnumerationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceDefinitionPrefix.
    def visitOccurrenceDefinitionPrefix(self, ctx:SysMLParser.OccurrenceDefinitionPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceDefinition.
    def visitOccurrenceDefinition(self, ctx:SysMLParser.OccurrenceDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#individualDefinition.
    def visitIndividualDefinition(self, ctx:SysMLParser.IndividualDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyMultiplicityMember.
    def visitEmptyMultiplicityMember(self, ctx:SysMLParser.EmptyMultiplicityMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyMultiplicity.
    def visitEmptyMultiplicity(self, ctx:SysMLParser.EmptyMultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceUsagePrefix.
    def visitOccurrenceUsagePrefix(self, ctx:SysMLParser.OccurrenceUsagePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#occurrenceUsage.
    def visitOccurrenceUsage(self, ctx:SysMLParser.OccurrenceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#individualUsage.
    def visitIndividualUsage(self, ctx:SysMLParser.IndividualUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#portionUsage.
    def visitPortionUsage(self, ctx:SysMLParser.PortionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#portionKindToken.
    def visitPortionKindToken(self, ctx:SysMLParser.PortionKindTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#eventOccurrenceUsage.
    def visitEventOccurrenceUsage(self, ctx:SysMLParser.EventOccurrenceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sourceSuccessionMember.
    def visitSourceSuccessionMember(self, ctx:SysMLParser.SourceSuccessionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sourceSuccession.
    def visitSourceSuccession(self, ctx:SysMLParser.SourceSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sourceEndMember.
    def visitSourceEndMember(self, ctx:SysMLParser.SourceEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sourceEnd.
    def visitSourceEnd(self, ctx:SysMLParser.SourceEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#itemDefinition.
    def visitItemDefinition(self, ctx:SysMLParser.ItemDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#itemUsage.
    def visitItemUsage(self, ctx:SysMLParser.ItemUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#partDefinition.
    def visitPartDefinition(self, ctx:SysMLParser.PartDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#partUsage.
    def visitPartUsage(self, ctx:SysMLParser.PartUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#portDefinition.
    def visitPortDefinition(self, ctx:SysMLParser.PortDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#conjugatedPortDefinitionMember.
    def visitConjugatedPortDefinitionMember(self, ctx:SysMLParser.ConjugatedPortDefinitionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#conjugatedPortDefinition.
    def visitConjugatedPortDefinition(self, ctx:SysMLParser.ConjugatedPortDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#portConjugation.
    def visitPortConjugation(self, ctx:SysMLParser.PortConjugationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#portUsage.
    def visitPortUsage(self, ctx:SysMLParser.PortUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#conjugatedPortTyping.
    def visitConjugatedPortTyping(self, ctx:SysMLParser.ConjugatedPortTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#connectionDefinition.
    def visitConnectionDefinition(self, ctx:SysMLParser.ConnectionDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#connectionUsage.
    def visitConnectionUsage(self, ctx:SysMLParser.ConnectionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#connectorPart.
    def visitConnectorPart(self, ctx:SysMLParser.ConnectorPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#binaryConnectorPart.
    def visitBinaryConnectorPart(self, ctx:SysMLParser.BinaryConnectorPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#naryConnectorPart.
    def visitNaryConnectorPart(self, ctx:SysMLParser.NaryConnectorPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#connectorEndMember.
    def visitConnectorEndMember(self, ctx:SysMLParser.ConnectorEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#connectorEnd.
    def visitConnectorEnd(self, ctx:SysMLParser.ConnectorEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedCrossMultiplicityMember.
    def visitOwnedCrossMultiplicityMember(self, ctx:SysMLParser.OwnedCrossMultiplicityMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedCrossMultiplicity.
    def visitOwnedCrossMultiplicity(self, ctx:SysMLParser.OwnedCrossMultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bindingConnectorAsUsage.
    def visitBindingConnectorAsUsage(self, ctx:SysMLParser.BindingConnectorAsUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#successionAsUsage.
    def visitSuccessionAsUsage(self, ctx:SysMLParser.SuccessionAsUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceDefinition.
    def visitInterfaceDefinition(self, ctx:SysMLParser.InterfaceDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceBody.
    def visitInterfaceBody(self, ctx:SysMLParser.InterfaceBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceBodyItem.
    def visitInterfaceBodyItem(self, ctx:SysMLParser.InterfaceBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceNonOccurrenceUsageMember.
    def visitInterfaceNonOccurrenceUsageMember(self, ctx:SysMLParser.InterfaceNonOccurrenceUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceNonOccurrenceUsageElement.
    def visitInterfaceNonOccurrenceUsageElement(self, ctx:SysMLParser.InterfaceNonOccurrenceUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceOccurrenceUsageMember.
    def visitInterfaceOccurrenceUsageMember(self, ctx:SysMLParser.InterfaceOccurrenceUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceOccurrenceUsageElement.
    def visitInterfaceOccurrenceUsageElement(self, ctx:SysMLParser.InterfaceOccurrenceUsageElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#defaultInterfaceEnd.
    def visitDefaultInterfaceEnd(self, ctx:SysMLParser.DefaultInterfaceEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceUsage.
    def visitInterfaceUsage(self, ctx:SysMLParser.InterfaceUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceUsageDeclaration.
    def visitInterfaceUsageDeclaration(self, ctx:SysMLParser.InterfaceUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfacePart.
    def visitInterfacePart(self, ctx:SysMLParser.InterfacePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#binaryInterfacePart.
    def visitBinaryInterfacePart(self, ctx:SysMLParser.BinaryInterfacePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#naryInterfacePart.
    def visitNaryInterfacePart(self, ctx:SysMLParser.NaryInterfacePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceEndMember.
    def visitInterfaceEndMember(self, ctx:SysMLParser.InterfaceEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#interfaceEnd.
    def visitInterfaceEnd(self, ctx:SysMLParser.InterfaceEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#allocationDefinition.
    def visitAllocationDefinition(self, ctx:SysMLParser.AllocationDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#allocationUsage.
    def visitAllocationUsage(self, ctx:SysMLParser.AllocationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#allocationUsageDeclaration.
    def visitAllocationUsageDeclaration(self, ctx:SysMLParser.AllocationUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowDefinition.
    def visitFlowDefinition(self, ctx:SysMLParser.FlowDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#message.
    def visitMessage(self, ctx:SysMLParser.MessageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#messageDeclaration.
    def visitMessageDeclaration(self, ctx:SysMLParser.MessageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#messageEventMember.
    def visitMessageEventMember(self, ctx:SysMLParser.MessageEventMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#messageEvent.
    def visitMessageEvent(self, ctx:SysMLParser.MessageEventContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowUsage.
    def visitFlowUsage(self, ctx:SysMLParser.FlowUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#successionFlowUsage.
    def visitSuccessionFlowUsage(self, ctx:SysMLParser.SuccessionFlowUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowDeclaration.
    def visitFlowDeclaration(self, ctx:SysMLParser.FlowDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowPayloadFeatureMember.
    def visitFlowPayloadFeatureMember(self, ctx:SysMLParser.FlowPayloadFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowPayloadFeature.
    def visitFlowPayloadFeature(self, ctx:SysMLParser.FlowPayloadFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#payloadFeature.
    def visitPayloadFeature(self, ctx:SysMLParser.PayloadFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#payloadFeatureSpecializationPart.
    def visitPayloadFeatureSpecializationPart(self, ctx:SysMLParser.PayloadFeatureSpecializationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowEndMember.
    def visitFlowEndMember(self, ctx:SysMLParser.FlowEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowEnd.
    def visitFlowEnd(self, ctx:SysMLParser.FlowEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowEndSubsetting.
    def visitFlowEndSubsetting(self, ctx:SysMLParser.FlowEndSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureChainPrefix.
    def visitFeatureChainPrefix(self, ctx:SysMLParser.FeatureChainPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowFeatureMember.
    def visitFlowFeatureMember(self, ctx:SysMLParser.FlowFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowFeature.
    def visitFlowFeature(self, ctx:SysMLParser.FlowFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#flowFeatureRedefinition.
    def visitFlowFeatureRedefinition(self, ctx:SysMLParser.FlowFeatureRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionDefinition.
    def visitActionDefinition(self, ctx:SysMLParser.ActionDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionBody.
    def visitActionBody(self, ctx:SysMLParser.ActionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionBodyItem.
    def visitActionBodyItem(self, ctx:SysMLParser.ActionBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonBehaviorBodyItem.
    def visitNonBehaviorBodyItem(self, ctx:SysMLParser.NonBehaviorBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionBehaviorMember.
    def visitActionBehaviorMember(self, ctx:SysMLParser.ActionBehaviorMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#initialNodeMember.
    def visitInitialNodeMember(self, ctx:SysMLParser.InitialNodeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionNodeMember.
    def visitActionNodeMember(self, ctx:SysMLParser.ActionNodeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionTargetSuccessionMember.
    def visitActionTargetSuccessionMember(self, ctx:SysMLParser.ActionTargetSuccessionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#guardedSuccessionMember.
    def visitGuardedSuccessionMember(self, ctx:SysMLParser.GuardedSuccessionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionUsage.
    def visitActionUsage(self, ctx:SysMLParser.ActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionUsageDeclaration.
    def visitActionUsageDeclaration(self, ctx:SysMLParser.ActionUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#performActionUsage.
    def visitPerformActionUsage(self, ctx:SysMLParser.PerformActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#performActionUsageDeclaration.
    def visitPerformActionUsageDeclaration(self, ctx:SysMLParser.PerformActionUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionNode.
    def visitActionNode(self, ctx:SysMLParser.ActionNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionNodeUsageDeclaration.
    def visitActionNodeUsageDeclaration(self, ctx:SysMLParser.ActionNodeUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionNodePrefix.
    def visitActionNodePrefix(self, ctx:SysMLParser.ActionNodePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#controlNode.
    def visitControlNode(self, ctx:SysMLParser.ControlNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#controlNodePrefix.
    def visitControlNodePrefix(self, ctx:SysMLParser.ControlNodePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#mergeNode.
    def visitMergeNode(self, ctx:SysMLParser.MergeNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#decisionNode.
    def visitDecisionNode(self, ctx:SysMLParser.DecisionNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#joinNode.
    def visitJoinNode(self, ctx:SysMLParser.JoinNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#forkNode.
    def visitForkNode(self, ctx:SysMLParser.ForkNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#acceptNode.
    def visitAcceptNode(self, ctx:SysMLParser.AcceptNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#acceptNodeDeclaration.
    def visitAcceptNodeDeclaration(self, ctx:SysMLParser.AcceptNodeDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#acceptParameterPart.
    def visitAcceptParameterPart(self, ctx:SysMLParser.AcceptParameterPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#payloadParameterMember.
    def visitPayloadParameterMember(self, ctx:SysMLParser.PayloadParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#payloadParameter.
    def visitPayloadParameter(self, ctx:SysMLParser.PayloadParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#triggerValuePart.
    def visitTriggerValuePart(self, ctx:SysMLParser.TriggerValuePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#triggerFeatureValue.
    def visitTriggerFeatureValue(self, ctx:SysMLParser.TriggerFeatureValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#triggerExpression.
    def visitTriggerExpression(self, ctx:SysMLParser.TriggerExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentMember.
    def visitArgumentMember(self, ctx:SysMLParser.ArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argument.
    def visitArgument(self, ctx:SysMLParser.ArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentValue.
    def visitArgumentValue(self, ctx:SysMLParser.ArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentExpressionMember.
    def visitArgumentExpressionMember(self, ctx:SysMLParser.ArgumentExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentExpression.
    def visitArgumentExpression(self, ctx:SysMLParser.ArgumentExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentExpressionValue.
    def visitArgumentExpressionValue(self, ctx:SysMLParser.ArgumentExpressionValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sendNode.
    def visitSendNode(self, ctx:SysMLParser.SendNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sendNodeDeclaration.
    def visitSendNodeDeclaration(self, ctx:SysMLParser.SendNodeDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#senderReceiverPart.
    def visitSenderReceiverPart(self, ctx:SysMLParser.SenderReceiverPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nodeParameterMember.
    def visitNodeParameterMember(self, ctx:SysMLParser.NodeParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nodeParameter.
    def visitNodeParameter(self, ctx:SysMLParser.NodeParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureBinding.
    def visitFeatureBinding(self, ctx:SysMLParser.FeatureBindingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyParameterMember.
    def visitEmptyParameterMember(self, ctx:SysMLParser.EmptyParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyUsage.
    def visitEmptyUsage(self, ctx:SysMLParser.EmptyUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assignmentNode.
    def visitAssignmentNode(self, ctx:SysMLParser.AssignmentNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assignmentNodeDeclaration.
    def visitAssignmentNodeDeclaration(self, ctx:SysMLParser.AssignmentNodeDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assignmentTargetMember.
    def visitAssignmentTargetMember(self, ctx:SysMLParser.AssignmentTargetMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assignmentTargetParameter.
    def visitAssignmentTargetParameter(self, ctx:SysMLParser.AssignmentTargetParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assignmentTargetBinding.
    def visitAssignmentTargetBinding(self, ctx:SysMLParser.AssignmentTargetBindingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureChainMember.
    def visitFeatureChainMember(self, ctx:SysMLParser.FeatureChainMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedFeatureChainMember.
    def visitOwnedFeatureChainMember(self, ctx:SysMLParser.OwnedFeatureChainMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#terminateNode.
    def visitTerminateNode(self, ctx:SysMLParser.TerminateNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ifNode.
    def visitIfNode(self, ctx:SysMLParser.IfNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#expressionParameterMember.
    def visitExpressionParameterMember(self, ctx:SysMLParser.ExpressionParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionBodyParameterMember.
    def visitActionBodyParameterMember(self, ctx:SysMLParser.ActionBodyParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionBodyParameter.
    def visitActionBodyParameter(self, ctx:SysMLParser.ActionBodyParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ifNodeParameterMember.
    def visitIfNodeParameterMember(self, ctx:SysMLParser.IfNodeParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#whileLoopNode.
    def visitWhileLoopNode(self, ctx:SysMLParser.WhileLoopNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#forLoopNode.
    def visitForLoopNode(self, ctx:SysMLParser.ForLoopNodeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#forVariableDeclarationMember.
    def visitForVariableDeclarationMember(self, ctx:SysMLParser.ForVariableDeclarationMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#forVariableDeclaration.
    def visitForVariableDeclaration(self, ctx:SysMLParser.ForVariableDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actionTargetSuccession.
    def visitActionTargetSuccession(self, ctx:SysMLParser.ActionTargetSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#targetSuccession.
    def visitTargetSuccession(self, ctx:SysMLParser.TargetSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#guardedTargetSuccession.
    def visitGuardedTargetSuccession(self, ctx:SysMLParser.GuardedTargetSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#defaultTargetSuccession.
    def visitDefaultTargetSuccession(self, ctx:SysMLParser.DefaultTargetSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#guardedSuccession.
    def visitGuardedSuccession(self, ctx:SysMLParser.GuardedSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateDefinition.
    def visitStateDefinition(self, ctx:SysMLParser.StateDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateDefBody.
    def visitStateDefBody(self, ctx:SysMLParser.StateDefBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateBodyItem.
    def visitStateBodyItem(self, ctx:SysMLParser.StateBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#entryActionMember.
    def visitEntryActionMember(self, ctx:SysMLParser.EntryActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#doActionMember.
    def visitDoActionMember(self, ctx:SysMLParser.DoActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#exitActionMember.
    def visitExitActionMember(self, ctx:SysMLParser.ExitActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#entryTransitionMember.
    def visitEntryTransitionMember(self, ctx:SysMLParser.EntryTransitionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateActionUsage.
    def visitStateActionUsage(self, ctx:SysMLParser.StateActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyActionUsage.
    def visitEmptyActionUsage(self, ctx:SysMLParser.EmptyActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#statePerformActionUsage.
    def visitStatePerformActionUsage(self, ctx:SysMLParser.StatePerformActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateAcceptActionUsage.
    def visitStateAcceptActionUsage(self, ctx:SysMLParser.StateAcceptActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateSendActionUsage.
    def visitStateSendActionUsage(self, ctx:SysMLParser.StateSendActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateAssignmentActionUsage.
    def visitStateAssignmentActionUsage(self, ctx:SysMLParser.StateAssignmentActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionUsageMember.
    def visitTransitionUsageMember(self, ctx:SysMLParser.TransitionUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#targetTransitionUsageMember.
    def visitTargetTransitionUsageMember(self, ctx:SysMLParser.TargetTransitionUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateUsage.
    def visitStateUsage(self, ctx:SysMLParser.StateUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stateUsageBody.
    def visitStateUsageBody(self, ctx:SysMLParser.StateUsageBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#exhibitStateUsage.
    def visitExhibitStateUsage(self, ctx:SysMLParser.ExhibitStateUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionUsage.
    def visitTransitionUsage(self, ctx:SysMLParser.TransitionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#targetTransitionUsage.
    def visitTargetTransitionUsage(self, ctx:SysMLParser.TargetTransitionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#triggerActionMember.
    def visitTriggerActionMember(self, ctx:SysMLParser.TriggerActionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#triggerAction.
    def visitTriggerAction(self, ctx:SysMLParser.TriggerActionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#guardExpressionMember.
    def visitGuardExpressionMember(self, ctx:SysMLParser.GuardExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#effectBehaviorMember.
    def visitEffectBehaviorMember(self, ctx:SysMLParser.EffectBehaviorMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#effectBehaviorUsage.
    def visitEffectBehaviorUsage(self, ctx:SysMLParser.EffectBehaviorUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionPerformActionUsage.
    def visitTransitionPerformActionUsage(self, ctx:SysMLParser.TransitionPerformActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionAcceptActionUsage.
    def visitTransitionAcceptActionUsage(self, ctx:SysMLParser.TransitionAcceptActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionSendActionUsage.
    def visitTransitionSendActionUsage(self, ctx:SysMLParser.TransitionSendActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionAssignmentActionUsage.
    def visitTransitionAssignmentActionUsage(self, ctx:SysMLParser.TransitionAssignmentActionUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionSuccessionMember.
    def visitTransitionSuccessionMember(self, ctx:SysMLParser.TransitionSuccessionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#transitionSuccession.
    def visitTransitionSuccession(self, ctx:SysMLParser.TransitionSuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyEndMember.
    def visitEmptyEndMember(self, ctx:SysMLParser.EmptyEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyFeature.
    def visitEmptyFeature(self, ctx:SysMLParser.EmptyFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationDefinition.
    def visitCalculationDefinition(self, ctx:SysMLParser.CalculationDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationUsage.
    def visitCalculationUsage(self, ctx:SysMLParser.CalculationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationUsageDeclaration.
    def visitCalculationUsageDeclaration(self, ctx:SysMLParser.CalculationUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationBody.
    def visitCalculationBody(self, ctx:SysMLParser.CalculationBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationBodyPart.
    def visitCalculationBodyPart(self, ctx:SysMLParser.CalculationBodyPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#calculationBodyItem.
    def visitCalculationBodyItem(self, ctx:SysMLParser.CalculationBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#returnParameterMember.
    def visitReturnParameterMember(self, ctx:SysMLParser.ReturnParameterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#resultExpressionMember.
    def visitResultExpressionMember(self, ctx:SysMLParser.ResultExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constraintDefinition.
    def visitConstraintDefinition(self, ctx:SysMLParser.ConstraintDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constraintUsage.
    def visitConstraintUsage(self, ctx:SysMLParser.ConstraintUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#assertConstraintUsage.
    def visitAssertConstraintUsage(self, ctx:SysMLParser.AssertConstraintUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constraintUsageDeclaration.
    def visitConstraintUsageDeclaration(self, ctx:SysMLParser.ConstraintUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementDefinition.
    def visitRequirementDefinition(self, ctx:SysMLParser.RequirementDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementBody.
    def visitRequirementBody(self, ctx:SysMLParser.RequirementBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementBodyItem.
    def visitRequirementBodyItem(self, ctx:SysMLParser.RequirementBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subjectMember.
    def visitSubjectMember(self, ctx:SysMLParser.SubjectMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#subjectUsage.
    def visitSubjectUsage(self, ctx:SysMLParser.SubjectUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementConstraintMember.
    def visitRequirementConstraintMember(self, ctx:SysMLParser.RequirementConstraintMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementKind.
    def visitRequirementKind(self, ctx:SysMLParser.RequirementKindContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementConstraintUsage.
    def visitRequirementConstraintUsage(self, ctx:SysMLParser.RequirementConstraintUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#framedConcernMember.
    def visitFramedConcernMember(self, ctx:SysMLParser.FramedConcernMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#framedConcernUsage.
    def visitFramedConcernUsage(self, ctx:SysMLParser.FramedConcernUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actorMember.
    def visitActorMember(self, ctx:SysMLParser.ActorMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#actorUsage.
    def visitActorUsage(self, ctx:SysMLParser.ActorUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stakeholderMember.
    def visitStakeholderMember(self, ctx:SysMLParser.StakeholderMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#stakeholderUsage.
    def visitStakeholderUsage(self, ctx:SysMLParser.StakeholderUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementUsage.
    def visitRequirementUsage(self, ctx:SysMLParser.RequirementUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#satisfyRequirementUsage.
    def visitSatisfyRequirementUsage(self, ctx:SysMLParser.SatisfyRequirementUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#satisfactionSubjectMember.
    def visitSatisfactionSubjectMember(self, ctx:SysMLParser.SatisfactionSubjectMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#satisfactionParameter.
    def visitSatisfactionParameter(self, ctx:SysMLParser.SatisfactionParameterContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#satisfactionFeatureValue.
    def visitSatisfactionFeatureValue(self, ctx:SysMLParser.SatisfactionFeatureValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#satisfactionReferenceExpression.
    def visitSatisfactionReferenceExpression(self, ctx:SysMLParser.SatisfactionReferenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#concernDefinition.
    def visitConcernDefinition(self, ctx:SysMLParser.ConcernDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#concernUsage.
    def visitConcernUsage(self, ctx:SysMLParser.ConcernUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#caseDefinition.
    def visitCaseDefinition(self, ctx:SysMLParser.CaseDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#caseUsage.
    def visitCaseUsage(self, ctx:SysMLParser.CaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#caseBody.
    def visitCaseBody(self, ctx:SysMLParser.CaseBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#caseBodyItem.
    def visitCaseBodyItem(self, ctx:SysMLParser.CaseBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#objectiveMember.
    def visitObjectiveMember(self, ctx:SysMLParser.ObjectiveMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#objectiveRequirementUsage.
    def visitObjectiveRequirementUsage(self, ctx:SysMLParser.ObjectiveRequirementUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#analysisCaseDefinition.
    def visitAnalysisCaseDefinition(self, ctx:SysMLParser.AnalysisCaseDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#analysisCaseUsage.
    def visitAnalysisCaseUsage(self, ctx:SysMLParser.AnalysisCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#verificationCaseDefinition.
    def visitVerificationCaseDefinition(self, ctx:SysMLParser.VerificationCaseDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#verificationCaseUsage.
    def visitVerificationCaseUsage(self, ctx:SysMLParser.VerificationCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementVerificationMember.
    def visitRequirementVerificationMember(self, ctx:SysMLParser.RequirementVerificationMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#requirementVerificationUsage.
    def visitRequirementVerificationUsage(self, ctx:SysMLParser.RequirementVerificationUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#useCaseDefinition.
    def visitUseCaseDefinition(self, ctx:SysMLParser.UseCaseDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#useCaseUsage.
    def visitUseCaseUsage(self, ctx:SysMLParser.UseCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#includeUseCaseUsage.
    def visitIncludeUseCaseUsage(self, ctx:SysMLParser.IncludeUseCaseUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewDefinition.
    def visitViewDefinition(self, ctx:SysMLParser.ViewDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewDefinitionBody.
    def visitViewDefinitionBody(self, ctx:SysMLParser.ViewDefinitionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewDefinitionBodyItem.
    def visitViewDefinitionBodyItem(self, ctx:SysMLParser.ViewDefinitionBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewRenderingMember.
    def visitViewRenderingMember(self, ctx:SysMLParser.ViewRenderingMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewRenderingUsage.
    def visitViewRenderingUsage(self, ctx:SysMLParser.ViewRenderingUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewUsage.
    def visitViewUsage(self, ctx:SysMLParser.ViewUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewBody.
    def visitViewBody(self, ctx:SysMLParser.ViewBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewBodyItem.
    def visitViewBodyItem(self, ctx:SysMLParser.ViewBodyItemContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#expose.
    def visitExpose(self, ctx:SysMLParser.ExposeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#membershipExpose.
    def visitMembershipExpose(self, ctx:SysMLParser.MembershipExposeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#namespaceExpose.
    def visitNamespaceExpose(self, ctx:SysMLParser.NamespaceExposeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewpointDefinition.
    def visitViewpointDefinition(self, ctx:SysMLParser.ViewpointDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#viewpointUsage.
    def visitViewpointUsage(self, ctx:SysMLParser.ViewpointUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#renderingDefinition.
    def visitRenderingDefinition(self, ctx:SysMLParser.RenderingDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#renderingUsage.
    def visitRenderingUsage(self, ctx:SysMLParser.RenderingUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataDefinition.
    def visitMetadataDefinition(self, ctx:SysMLParser.MetadataDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#prefixMetadataAnnotation.
    def visitPrefixMetadataAnnotation(self, ctx:SysMLParser.PrefixMetadataAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#prefixMetadataMember.
    def visitPrefixMetadataMember(self, ctx:SysMLParser.PrefixMetadataMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#prefixMetadataUsage.
    def visitPrefixMetadataUsage(self, ctx:SysMLParser.PrefixMetadataUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataUsage.
    def visitMetadataUsage(self, ctx:SysMLParser.MetadataUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataUsageDeclaration.
    def visitMetadataUsageDeclaration(self, ctx:SysMLParser.MetadataUsageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataBody.
    def visitMetadataBody(self, ctx:SysMLParser.MetadataBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataBodyUsageMember.
    def visitMetadataBodyUsageMember(self, ctx:SysMLParser.MetadataBodyUsageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataBodyUsage.
    def visitMetadataBodyUsage(self, ctx:SysMLParser.MetadataBodyUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#extendedDefinition.
    def visitExtendedDefinition(self, ctx:SysMLParser.ExtendedDefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#extendedUsage.
    def visitExtendedUsage(self, ctx:SysMLParser.ExtendedUsageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataFeature.
    def visitMetadataFeature(self, ctx:SysMLParser.MetadataFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataFeatureDeclaration.
    def visitMetadataFeatureDeclaration(self, ctx:SysMLParser.MetadataFeatureDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedExpressionReferenceMember.
    def visitOwnedExpressionReferenceMember(self, ctx:SysMLParser.OwnedExpressionReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedExpressionReference.
    def visitOwnedExpressionReference(self, ctx:SysMLParser.OwnedExpressionReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedExpressionMember.
    def visitOwnedExpressionMember(self, ctx:SysMLParser.OwnedExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#ownedExpression.
    def visitOwnedExpression(self, ctx:SysMLParser.OwnedExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#conditionalBinaryOperator.
    def visitConditionalBinaryOperator(self, ctx:SysMLParser.ConditionalBinaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#binaryOperator.
    def visitBinaryOperator(self, ctx:SysMLParser.BinaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#equalityOperator.
    def visitEqualityOperator(self, ctx:SysMLParser.EqualityOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#relationalOperator.
    def visitRelationalOperator(self, ctx:SysMLParser.RelationalOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#additiveOperator.
    def visitAdditiveOperator(self, ctx:SysMLParser.AdditiveOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#multiplicativeOperator.
    def visitMultiplicativeOperator(self, ctx:SysMLParser.MultiplicativeOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#exponentialOperator.
    def visitExponentialOperator(self, ctx:SysMLParser.ExponentialOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bitwiseOperator.
    def visitBitwiseOperator(self, ctx:SysMLParser.BitwiseOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#rangeOperator.
    def visitRangeOperator(self, ctx:SysMLParser.RangeOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#unaryOperator.
    def visitUnaryOperator(self, ctx:SysMLParser.UnaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#classificationTestOperator.
    def visitClassificationTestOperator(self, ctx:SysMLParser.ClassificationTestOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#castOperator.
    def visitCastOperator(self, ctx:SysMLParser.CastOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metaclassificationTestOperator.
    def visitMetaclassificationTestOperator(self, ctx:SysMLParser.MetaclassificationTestOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metacastOperator.
    def visitMetacastOperator(self, ctx:SysMLParser.MetacastOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#typeReferenceMember.
    def visitTypeReferenceMember(self, ctx:SysMLParser.TypeReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#typeResultMember.
    def visitTypeResultMember(self, ctx:SysMLParser.TypeResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#typeReference.
    def visitTypeReference(self, ctx:SysMLParser.TypeReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#referenceTyping.
    def visitReferenceTyping(self, ctx:SysMLParser.ReferenceTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#emptyResultMember.
    def visitEmptyResultMember(self, ctx:SysMLParser.EmptyResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataArgumentMember.
    def visitMetadataArgumentMember(self, ctx:SysMLParser.MetadataArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataArgument.
    def visitMetadataArgument(self, ctx:SysMLParser.MetadataArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataValue.
    def visitMetadataValue(self, ctx:SysMLParser.MetadataValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataReference.
    def visitMetadataReference(self, ctx:SysMLParser.MetadataReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#primaryExpression.
    def visitPrimaryExpression(self, ctx:SysMLParser.PrimaryExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#primaryArgumentValue.
    def visitPrimaryArgumentValue(self, ctx:SysMLParser.PrimaryArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#primaryArgument.
    def visitPrimaryArgument(self, ctx:SysMLParser.PrimaryArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#primaryArgumentMember.
    def visitPrimaryArgumentMember(self, ctx:SysMLParser.PrimaryArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonFeatureChainPrimaryExpression.
    def visitNonFeatureChainPrimaryExpression(self, ctx:SysMLParser.NonFeatureChainPrimaryExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonFeatureChainPrimaryArgumentValue.
    def visitNonFeatureChainPrimaryArgumentValue(self, ctx:SysMLParser.NonFeatureChainPrimaryArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonFeatureChainPrimaryArgument.
    def visitNonFeatureChainPrimaryArgument(self, ctx:SysMLParser.NonFeatureChainPrimaryArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nonFeatureChainPrimaryArgumentMember.
    def visitNonFeatureChainPrimaryArgumentMember(self, ctx:SysMLParser.NonFeatureChainPrimaryArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bracketExpression.
    def visitBracketExpression(self, ctx:SysMLParser.BracketExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#indexExpression.
    def visitIndexExpression(self, ctx:SysMLParser.IndexExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sequenceExpression.
    def visitSequenceExpression(self, ctx:SysMLParser.SequenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sequenceExpressionList.
    def visitSequenceExpressionList(self, ctx:SysMLParser.SequenceExpressionListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sequenceOperatorExpression.
    def visitSequenceOperatorExpression(self, ctx:SysMLParser.SequenceOperatorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#sequenceExpressionListMember.
    def visitSequenceExpressionListMember(self, ctx:SysMLParser.SequenceExpressionListMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureChainExpression.
    def visitFeatureChainExpression(self, ctx:SysMLParser.FeatureChainExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#collectExpression.
    def visitCollectExpression(self, ctx:SysMLParser.CollectExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#selectExpression.
    def visitSelectExpression(self, ctx:SysMLParser.SelectExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionOperationExpression.
    def visitFunctionOperationExpression(self, ctx:SysMLParser.FunctionOperationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bodyArgumentMember.
    def visitBodyArgumentMember(self, ctx:SysMLParser.BodyArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bodyArgument.
    def visitBodyArgument(self, ctx:SysMLParser.BodyArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bodyArgumentValue.
    def visitBodyArgumentValue(self, ctx:SysMLParser.BodyArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReferenceArgumentMember.
    def visitFunctionReferenceArgumentMember(self, ctx:SysMLParser.FunctionReferenceArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReferenceArgument.
    def visitFunctionReferenceArgument(self, ctx:SysMLParser.FunctionReferenceArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReferenceArgumentValue.
    def visitFunctionReferenceArgumentValue(self, ctx:SysMLParser.FunctionReferenceArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReferenceExpression.
    def visitFunctionReferenceExpression(self, ctx:SysMLParser.FunctionReferenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReferenceMember.
    def visitFunctionReferenceMember(self, ctx:SysMLParser.FunctionReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#functionReference.
    def visitFunctionReference(self, ctx:SysMLParser.FunctionReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#invocationTypeMember.
    def visitInvocationTypeMember(self, ctx:SysMLParser.InvocationTypeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#invocationType.
    def visitInvocationType(self, ctx:SysMLParser.InvocationTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#baseExpression.
    def visitBaseExpression(self, ctx:SysMLParser.BaseExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#nullExpression.
    def visitNullExpression(self, ctx:SysMLParser.NullExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureReferenceExpression.
    def visitFeatureReferenceExpression(self, ctx:SysMLParser.FeatureReferenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureReferenceMember.
    def visitFeatureReferenceMember(self, ctx:SysMLParser.FeatureReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#featureReference.
    def visitFeatureReference(self, ctx:SysMLParser.FeatureReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#metadataAccessExpression.
    def visitMetadataAccessExpression(self, ctx:SysMLParser.MetadataAccessExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#elementReferenceMember.
    def visitElementReferenceMember(self, ctx:SysMLParser.ElementReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#invocationExpression.
    def visitInvocationExpression(self, ctx:SysMLParser.InvocationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constructorExpression.
    def visitConstructorExpression(self, ctx:SysMLParser.ConstructorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constructorResultMember.
    def visitConstructorResultMember(self, ctx:SysMLParser.ConstructorResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#constructorResult.
    def visitConstructorResult(self, ctx:SysMLParser.ConstructorResultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#instantiatedTypeMember.
    def visitInstantiatedTypeMember(self, ctx:SysMLParser.InstantiatedTypeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#instantiatedTypeReference.
    def visitInstantiatedTypeReference(self, ctx:SysMLParser.InstantiatedTypeReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#argumentList.
    def visitArgumentList(self, ctx:SysMLParser.ArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#positionalArgumentList.
    def visitPositionalArgumentList(self, ctx:SysMLParser.PositionalArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#namedArgumentList.
    def visitNamedArgumentList(self, ctx:SysMLParser.NamedArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#namedArgumentMember.
    def visitNamedArgumentMember(self, ctx:SysMLParser.NamedArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#namedArgument.
    def visitNamedArgument(self, ctx:SysMLParser.NamedArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#parameterRedefinition.
    def visitParameterRedefinition(self, ctx:SysMLParser.ParameterRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#bodyExpression.
    def visitBodyExpression(self, ctx:SysMLParser.BodyExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#expressionBodyMember.
    def visitExpressionBodyMember(self, ctx:SysMLParser.ExpressionBodyMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#expressionBody.
    def visitExpressionBody(self, ctx:SysMLParser.ExpressionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalExpression.
    def visitLiteralExpression(self, ctx:SysMLParser.LiteralExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalBoolean.
    def visitLiteralBoolean(self, ctx:SysMLParser.LiteralBooleanContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#booleanValue.
    def visitBooleanValue(self, ctx:SysMLParser.BooleanValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalString.
    def visitLiteralString(self, ctx:SysMLParser.LiteralStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalInteger.
    def visitLiteralInteger(self, ctx:SysMLParser.LiteralIntegerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalReal.
    def visitLiteralReal(self, ctx:SysMLParser.LiteralRealContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#realValue.
    def visitRealValue(self, ctx:SysMLParser.RealValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by SysMLParser#literalInfinity.
    def visitLiteralInfinity(self, ctx:SysMLParser.LiteralInfinityContext):
        return self.visitChildren(ctx)



del SysMLParser