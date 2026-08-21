# Generated from grammars/KerML.g4 by ANTLR 4.13.2
from antlr4 import *
if "." in __name__:
    from .KerMLParser import KerMLParser
else:
    from KerMLParser import KerMLParser

# This class defines a complete generic visitor for a parse tree produced by KerMLParser.

class KerMLVisitor(ParseTreeVisitor):

    # Visit a parse tree produced by KerMLParser#typedByToken.
    def visitTypedByToken(self, ctx:KerMLParser.TypedByTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#specializesToken.
    def visitSpecializesToken(self, ctx:KerMLParser.SpecializesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#subsetsToken.
    def visitSubsetsToken(self, ctx:KerMLParser.SubsetsTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#referencesToken.
    def visitReferencesToken(self, ctx:KerMLParser.ReferencesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#crossesToken.
    def visitCrossesToken(self, ctx:KerMLParser.CrossesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#redefinesToken.
    def visitRedefinesToken(self, ctx:KerMLParser.RedefinesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#conjugatesToken.
    def visitConjugatesToken(self, ctx:KerMLParser.ConjugatesTokenContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#identification.
    def visitIdentification(self, ctx:KerMLParser.IdentificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#relationshipBody.
    def visitRelationshipBody(self, ctx:KerMLParser.RelationshipBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#relationshipOwnedElement.
    def visitRelationshipOwnedElement(self, ctx:KerMLParser.RelationshipOwnedElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedRelatedElement.
    def visitOwnedRelatedElement(self, ctx:KerMLParser.OwnedRelatedElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#dependency.
    def visitDependency(self, ctx:KerMLParser.DependencyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#annotation.
    def visitAnnotation(self, ctx:KerMLParser.AnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedAnnotation.
    def visitOwnedAnnotation(self, ctx:KerMLParser.OwnedAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#annotatingElement.
    def visitAnnotatingElement(self, ctx:KerMLParser.AnnotatingElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#comment.
    def visitComment(self, ctx:KerMLParser.CommentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#documentation.
    def visitDocumentation(self, ctx:KerMLParser.DocumentationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#textualRepresentation.
    def visitTextualRepresentation(self, ctx:KerMLParser.TextualRepresentationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#rootNamespace.
    def visitRootNamespace(self, ctx:KerMLParser.RootNamespaceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespace.
    def visitNamespace(self, ctx:KerMLParser.NamespaceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceDeclaration.
    def visitNamespaceDeclaration(self, ctx:KerMLParser.NamespaceDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceBody.
    def visitNamespaceBody(self, ctx:KerMLParser.NamespaceBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceBodyElement.
    def visitNamespaceBodyElement(self, ctx:KerMLParser.NamespaceBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#memberPrefix.
    def visitMemberPrefix(self, ctx:KerMLParser.MemberPrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#visibilityIndicator.
    def visitVisibilityIndicator(self, ctx:KerMLParser.VisibilityIndicatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceMember.
    def visitNamespaceMember(self, ctx:KerMLParser.NamespaceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureMember.
    def visitNonFeatureMember(self, ctx:KerMLParser.NonFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceFeatureMember.
    def visitNamespaceFeatureMember(self, ctx:KerMLParser.NamespaceFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#aliasMember.
    def visitAliasMember(self, ctx:KerMLParser.AliasMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#qualifiedName.
    def visitQualifiedName(self, ctx:KerMLParser.QualifiedNameContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#import_.
    def visitImport_(self, ctx:KerMLParser.Import_Context):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#importDeclaration.
    def visitImportDeclaration(self, ctx:KerMLParser.ImportDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#membershipImport.
    def visitMembershipImport(self, ctx:KerMLParser.MembershipImportContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namespaceImport.
    def visitNamespaceImport(self, ctx:KerMLParser.NamespaceImportContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#filterPackageImport.
    def visitFilterPackageImport(self, ctx:KerMLParser.FilterPackageImportContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#filterPackageMember.
    def visitFilterPackageMember(self, ctx:KerMLParser.FilterPackageMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#memberElement.
    def visitMemberElement(self, ctx:KerMLParser.MemberElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureElement.
    def visitNonFeatureElement(self, ctx:KerMLParser.NonFeatureElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureElement.
    def visitFeatureElement(self, ctx:KerMLParser.FeatureElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#type.
    def visitType(self, ctx:KerMLParser.TypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typePrefix.
    def visitTypePrefix(self, ctx:KerMLParser.TypePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeDeclaration.
    def visitTypeDeclaration(self, ctx:KerMLParser.TypeDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#specializationPart.
    def visitSpecializationPart(self, ctx:KerMLParser.SpecializationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#conjugationPart.
    def visitConjugationPart(self, ctx:KerMLParser.ConjugationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeRelationshipPart.
    def visitTypeRelationshipPart(self, ctx:KerMLParser.TypeRelationshipPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#disjoiningPart.
    def visitDisjoiningPart(self, ctx:KerMLParser.DisjoiningPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#unioningPart.
    def visitUnioningPart(self, ctx:KerMLParser.UnioningPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#intersectingPart.
    def visitIntersectingPart(self, ctx:KerMLParser.IntersectingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#differencingPart.
    def visitDifferencingPart(self, ctx:KerMLParser.DifferencingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeBody.
    def visitTypeBody(self, ctx:KerMLParser.TypeBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeBodyElement.
    def visitTypeBodyElement(self, ctx:KerMLParser.TypeBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#specialization.
    def visitSpecialization(self, ctx:KerMLParser.SpecializationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedSpecialization.
    def visitOwnedSpecialization(self, ctx:KerMLParser.OwnedSpecializationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#specificType.
    def visitSpecificType(self, ctx:KerMLParser.SpecificTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#generalType.
    def visitGeneralType(self, ctx:KerMLParser.GeneralTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#conjugation.
    def visitConjugation(self, ctx:KerMLParser.ConjugationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedConjugation.
    def visitOwnedConjugation(self, ctx:KerMLParser.OwnedConjugationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#disjoining.
    def visitDisjoining(self, ctx:KerMLParser.DisjoiningContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedDisjoining.
    def visitOwnedDisjoining(self, ctx:KerMLParser.OwnedDisjoiningContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#unioning.
    def visitUnioning(self, ctx:KerMLParser.UnioningContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#intersecting.
    def visitIntersecting(self, ctx:KerMLParser.IntersectingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#differencing.
    def visitDifferencing(self, ctx:KerMLParser.DifferencingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureMember.
    def visitFeatureMember(self, ctx:KerMLParser.FeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeFeatureMember.
    def visitTypeFeatureMember(self, ctx:KerMLParser.TypeFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureMember.
    def visitOwnedFeatureMember(self, ctx:KerMLParser.OwnedFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#classifier.
    def visitClassifier(self, ctx:KerMLParser.ClassifierContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#classifierDeclaration.
    def visitClassifierDeclaration(self, ctx:KerMLParser.ClassifierDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#superclassingPart.
    def visitSuperclassingPart(self, ctx:KerMLParser.SuperclassingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#subclassification.
    def visitSubclassification(self, ctx:KerMLParser.SubclassificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedSubclassification.
    def visitOwnedSubclassification(self, ctx:KerMLParser.OwnedSubclassificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#feature.
    def visitFeature(self, ctx:KerMLParser.FeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#endFeaturePrefix.
    def visitEndFeaturePrefix(self, ctx:KerMLParser.EndFeaturePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#basicFeaturePrefix.
    def visitBasicFeaturePrefix(self, ctx:KerMLParser.BasicFeaturePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featurePrefix.
    def visitFeaturePrefix(self, ctx:KerMLParser.FeaturePrefixContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedCrossFeatureMember.
    def visitOwnedCrossFeatureMember(self, ctx:KerMLParser.OwnedCrossFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedCrossFeature.
    def visitOwnedCrossFeature(self, ctx:KerMLParser.OwnedCrossFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureDirection.
    def visitFeatureDirection(self, ctx:KerMLParser.FeatureDirectionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureDeclaration.
    def visitFeatureDeclaration(self, ctx:KerMLParser.FeatureDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureIdentification.
    def visitFeatureIdentification(self, ctx:KerMLParser.FeatureIdentificationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureRelationshipPart.
    def visitFeatureRelationshipPart(self, ctx:KerMLParser.FeatureRelationshipPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#chainingPart.
    def visitChainingPart(self, ctx:KerMLParser.ChainingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#invertingPart.
    def visitInvertingPart(self, ctx:KerMLParser.InvertingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeFeaturingPart.
    def visitTypeFeaturingPart(self, ctx:KerMLParser.TypeFeaturingPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureSpecializationPart.
    def visitFeatureSpecializationPart(self, ctx:KerMLParser.FeatureSpecializationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicityPart.
    def visitMultiplicityPart(self, ctx:KerMLParser.MultiplicityPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureSpecialization.
    def visitFeatureSpecialization(self, ctx:KerMLParser.FeatureSpecializationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typings.
    def visitTypings(self, ctx:KerMLParser.TypingsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typedBy.
    def visitTypedBy(self, ctx:KerMLParser.TypedByContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#subsettings.
    def visitSubsettings(self, ctx:KerMLParser.SubsettingsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#subsets.
    def visitSubsets(self, ctx:KerMLParser.SubsetsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#references.
    def visitReferences(self, ctx:KerMLParser.ReferencesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#crosses.
    def visitCrosses(self, ctx:KerMLParser.CrossesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#redefinitions.
    def visitRedefinitions(self, ctx:KerMLParser.RedefinitionsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#redefines.
    def visitRedefines(self, ctx:KerMLParser.RedefinesContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureTyping.
    def visitFeatureTyping(self, ctx:KerMLParser.FeatureTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureTyping.
    def visitOwnedFeatureTyping(self, ctx:KerMLParser.OwnedFeatureTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#subsetting.
    def visitSubsetting(self, ctx:KerMLParser.SubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedSubsetting.
    def visitOwnedSubsetting(self, ctx:KerMLParser.OwnedSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedReferenceSubsetting.
    def visitOwnedReferenceSubsetting(self, ctx:KerMLParser.OwnedReferenceSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedCrossSubsetting.
    def visitOwnedCrossSubsetting(self, ctx:KerMLParser.OwnedCrossSubsettingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#redefinition.
    def visitRedefinition(self, ctx:KerMLParser.RedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedRedefinition.
    def visitOwnedRedefinition(self, ctx:KerMLParser.OwnedRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureChain.
    def visitOwnedFeatureChain(self, ctx:KerMLParser.OwnedFeatureChainContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureChain.
    def visitFeatureChain(self, ctx:KerMLParser.FeatureChainContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureChaining.
    def visitOwnedFeatureChaining(self, ctx:KerMLParser.OwnedFeatureChainingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureInverting.
    def visitFeatureInverting(self, ctx:KerMLParser.FeatureInvertingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureInverting.
    def visitOwnedFeatureInverting(self, ctx:KerMLParser.OwnedFeatureInvertingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeFeaturing.
    def visitTypeFeaturing(self, ctx:KerMLParser.TypeFeaturingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedTypeFeaturing.
    def visitOwnedTypeFeaturing(self, ctx:KerMLParser.OwnedTypeFeaturingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#datatype.
    def visitDatatype(self, ctx:KerMLParser.DatatypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#class.
    def visitClass(self, ctx:KerMLParser.ClassContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#structure.
    def visitStructure(self, ctx:KerMLParser.StructureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#association.
    def visitAssociation(self, ctx:KerMLParser.AssociationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#associationStructure.
    def visitAssociationStructure(self, ctx:KerMLParser.AssociationStructureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#connector.
    def visitConnector(self, ctx:KerMLParser.ConnectorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#connectorDeclaration.
    def visitConnectorDeclaration(self, ctx:KerMLParser.ConnectorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#binaryConnectorDeclaration.
    def visitBinaryConnectorDeclaration(self, ctx:KerMLParser.BinaryConnectorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#naryConnectorDeclaration.
    def visitNaryConnectorDeclaration(self, ctx:KerMLParser.NaryConnectorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#connectorEndMember.
    def visitConnectorEndMember(self, ctx:KerMLParser.ConnectorEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#connectorEnd.
    def visitConnectorEnd(self, ctx:KerMLParser.ConnectorEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedCrossMultiplicityMember.
    def visitOwnedCrossMultiplicityMember(self, ctx:KerMLParser.OwnedCrossMultiplicityMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedCrossMultiplicity.
    def visitOwnedCrossMultiplicity(self, ctx:KerMLParser.OwnedCrossMultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bindingConnector.
    def visitBindingConnector(self, ctx:KerMLParser.BindingConnectorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bindingConnectorDeclaration.
    def visitBindingConnectorDeclaration(self, ctx:KerMLParser.BindingConnectorDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#succession.
    def visitSuccession(self, ctx:KerMLParser.SuccessionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#successionDeclaration.
    def visitSuccessionDeclaration(self, ctx:KerMLParser.SuccessionDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#behavior.
    def visitBehavior(self, ctx:KerMLParser.BehaviorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#step.
    def visitStep(self, ctx:KerMLParser.StepContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#function.
    def visitFunction(self, ctx:KerMLParser.FunctionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionBody.
    def visitFunctionBody(self, ctx:KerMLParser.FunctionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionBodyPart.
    def visitFunctionBodyPart(self, ctx:KerMLParser.FunctionBodyPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#returnFeatureMember.
    def visitReturnFeatureMember(self, ctx:KerMLParser.ReturnFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#resultExpressionMember.
    def visitResultExpressionMember(self, ctx:KerMLParser.ResultExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#expression.
    def visitExpression(self, ctx:KerMLParser.ExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#predicate.
    def visitPredicate(self, ctx:KerMLParser.PredicateContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#booleanExpression.
    def visitBooleanExpression(self, ctx:KerMLParser.BooleanExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#invariant.
    def visitInvariant(self, ctx:KerMLParser.InvariantContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedExpressionReferenceMember.
    def visitOwnedExpressionReferenceMember(self, ctx:KerMLParser.OwnedExpressionReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedExpressionReference.
    def visitOwnedExpressionReference(self, ctx:KerMLParser.OwnedExpressionReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedExpressionMember.
    def visitOwnedExpressionMember(self, ctx:KerMLParser.OwnedExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedExpression.
    def visitOwnedExpression(self, ctx:KerMLParser.OwnedExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#conditionalBinaryOperator.
    def visitConditionalBinaryOperator(self, ctx:KerMLParser.ConditionalBinaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#binaryOperatorExpression.
    def visitBinaryOperatorExpression(self, ctx:KerMLParser.BinaryOperatorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#binaryOperator.
    def visitBinaryOperator(self, ctx:KerMLParser.BinaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#equalityOperator.
    def visitEqualityOperator(self, ctx:KerMLParser.EqualityOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#relationalOperator.
    def visitRelationalOperator(self, ctx:KerMLParser.RelationalOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#additiveOperator.
    def visitAdditiveOperator(self, ctx:KerMLParser.AdditiveOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicativeOperator.
    def visitMultiplicativeOperator(self, ctx:KerMLParser.MultiplicativeOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#exponentialOperator.
    def visitExponentialOperator(self, ctx:KerMLParser.ExponentialOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bitwiseOperator.
    def visitBitwiseOperator(self, ctx:KerMLParser.BitwiseOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#rangeOperator.
    def visitRangeOperator(self, ctx:KerMLParser.RangeOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#unaryOperatorExpression.
    def visitUnaryOperatorExpression(self, ctx:KerMLParser.UnaryOperatorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#unaryOperator.
    def visitUnaryOperator(self, ctx:KerMLParser.UnaryOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#classificationExpression.
    def visitClassificationExpression(self, ctx:KerMLParser.ClassificationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#classificationTestOperator.
    def visitClassificationTestOperator(self, ctx:KerMLParser.ClassificationTestOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#castOperator.
    def visitCastOperator(self, ctx:KerMLParser.CastOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metaclassificationExpression.
    def visitMetaclassificationExpression(self, ctx:KerMLParser.MetaclassificationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentMember.
    def visitArgumentMember(self, ctx:KerMLParser.ArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argument.
    def visitArgument(self, ctx:KerMLParser.ArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentValue.
    def visitArgumentValue(self, ctx:KerMLParser.ArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentExpressionMember.
    def visitArgumentExpressionMember(self, ctx:KerMLParser.ArgumentExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentExpression.
    def visitArgumentExpression(self, ctx:KerMLParser.ArgumentExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentExpressionValue.
    def visitArgumentExpressionValue(self, ctx:KerMLParser.ArgumentExpressionValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataArgumentMember.
    def visitMetadataArgumentMember(self, ctx:KerMLParser.MetadataArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataArgument.
    def visitMetadataArgument(self, ctx:KerMLParser.MetadataArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataValue.
    def visitMetadataValue(self, ctx:KerMLParser.MetadataValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataReference.
    def visitMetadataReference(self, ctx:KerMLParser.MetadataReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metaclassificationTestOperator.
    def visitMetaclassificationTestOperator(self, ctx:KerMLParser.MetaclassificationTestOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metacastOperator.
    def visitMetacastOperator(self, ctx:KerMLParser.MetacastOperatorContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#extentExpression.
    def visitExtentExpression(self, ctx:KerMLParser.ExtentExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeReferenceMember.
    def visitTypeReferenceMember(self, ctx:KerMLParser.TypeReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeResultMember.
    def visitTypeResultMember(self, ctx:KerMLParser.TypeResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#typeReference.
    def visitTypeReference(self, ctx:KerMLParser.TypeReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#referenceTyping.
    def visitReferenceTyping(self, ctx:KerMLParser.ReferenceTypingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#emptyResultMember.
    def visitEmptyResultMember(self, ctx:KerMLParser.EmptyResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#emptyFeature.
    def visitEmptyFeature(self, ctx:KerMLParser.EmptyFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#primaryExpression.
    def visitPrimaryExpression(self, ctx:KerMLParser.PrimaryExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#primaryArgumentValue.
    def visitPrimaryArgumentValue(self, ctx:KerMLParser.PrimaryArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#primaryArgument.
    def visitPrimaryArgument(self, ctx:KerMLParser.PrimaryArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#primaryArgumentMember.
    def visitPrimaryArgumentMember(self, ctx:KerMLParser.PrimaryArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureChainPrimaryExpression.
    def visitNonFeatureChainPrimaryExpression(self, ctx:KerMLParser.NonFeatureChainPrimaryExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureChainPrimaryArgumentValue.
    def visitNonFeatureChainPrimaryArgumentValue(self, ctx:KerMLParser.NonFeatureChainPrimaryArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureChainPrimaryArgument.
    def visitNonFeatureChainPrimaryArgument(self, ctx:KerMLParser.NonFeatureChainPrimaryArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nonFeatureChainPrimaryArgumentMember.
    def visitNonFeatureChainPrimaryArgumentMember(self, ctx:KerMLParser.NonFeatureChainPrimaryArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bracketExpression.
    def visitBracketExpression(self, ctx:KerMLParser.BracketExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#indexExpression.
    def visitIndexExpression(self, ctx:KerMLParser.IndexExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#sequenceExpression.
    def visitSequenceExpression(self, ctx:KerMLParser.SequenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#sequenceExpressionList.
    def visitSequenceExpressionList(self, ctx:KerMLParser.SequenceExpressionListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#sequenceOperatorExpression.
    def visitSequenceOperatorExpression(self, ctx:KerMLParser.SequenceOperatorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#sequenceExpressionListMember.
    def visitSequenceExpressionListMember(self, ctx:KerMLParser.SequenceExpressionListMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureChainExpression.
    def visitFeatureChainExpression(self, ctx:KerMLParser.FeatureChainExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#collectExpression.
    def visitCollectExpression(self, ctx:KerMLParser.CollectExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#selectExpression.
    def visitSelectExpression(self, ctx:KerMLParser.SelectExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionOperationExpression.
    def visitFunctionOperationExpression(self, ctx:KerMLParser.FunctionOperationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bodyArgumentMember.
    def visitBodyArgumentMember(self, ctx:KerMLParser.BodyArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bodyArgument.
    def visitBodyArgument(self, ctx:KerMLParser.BodyArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bodyArgumentValue.
    def visitBodyArgumentValue(self, ctx:KerMLParser.BodyArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReferenceArgumentMember.
    def visitFunctionReferenceArgumentMember(self, ctx:KerMLParser.FunctionReferenceArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReferenceArgument.
    def visitFunctionReferenceArgument(self, ctx:KerMLParser.FunctionReferenceArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReferenceArgumentValue.
    def visitFunctionReferenceArgumentValue(self, ctx:KerMLParser.FunctionReferenceArgumentValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReferenceExpression.
    def visitFunctionReferenceExpression(self, ctx:KerMLParser.FunctionReferenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReferenceMember.
    def visitFunctionReferenceMember(self, ctx:KerMLParser.FunctionReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#functionReference.
    def visitFunctionReference(self, ctx:KerMLParser.FunctionReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureChainMember.
    def visitFeatureChainMember(self, ctx:KerMLParser.FeatureChainMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#invocationTypeMember.
    def visitInvocationTypeMember(self, ctx:KerMLParser.InvocationTypeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#invocationType.
    def visitInvocationType(self, ctx:KerMLParser.InvocationTypeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#baseExpression.
    def visitBaseExpression(self, ctx:KerMLParser.BaseExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#nullExpression.
    def visitNullExpression(self, ctx:KerMLParser.NullExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureReferenceExpression.
    def visitFeatureReferenceExpression(self, ctx:KerMLParser.FeatureReferenceExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureReferenceMember.
    def visitFeatureReferenceMember(self, ctx:KerMLParser.FeatureReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureReference.
    def visitFeatureReference(self, ctx:KerMLParser.FeatureReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataAccessExpression.
    def visitMetadataAccessExpression(self, ctx:KerMLParser.MetadataAccessExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#elementReferenceMember.
    def visitElementReferenceMember(self, ctx:KerMLParser.ElementReferenceMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#invocationExpression.
    def visitInvocationExpression(self, ctx:KerMLParser.InvocationExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#constructorExpression.
    def visitConstructorExpression(self, ctx:KerMLParser.ConstructorExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#constructorResultMember.
    def visitConstructorResultMember(self, ctx:KerMLParser.ConstructorResultMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#constructorResult.
    def visitConstructorResult(self, ctx:KerMLParser.ConstructorResultContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#instantiatedTypeMember.
    def visitInstantiatedTypeMember(self, ctx:KerMLParser.InstantiatedTypeMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#instantiatedTypeReference.
    def visitInstantiatedTypeReference(self, ctx:KerMLParser.InstantiatedTypeReferenceContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedFeatureChainMember.
    def visitOwnedFeatureChainMember(self, ctx:KerMLParser.OwnedFeatureChainMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#argumentList.
    def visitArgumentList(self, ctx:KerMLParser.ArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#positionalArgumentList.
    def visitPositionalArgumentList(self, ctx:KerMLParser.PositionalArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namedArgumentList.
    def visitNamedArgumentList(self, ctx:KerMLParser.NamedArgumentListContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namedArgumentMember.
    def visitNamedArgumentMember(self, ctx:KerMLParser.NamedArgumentMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#namedArgument.
    def visitNamedArgument(self, ctx:KerMLParser.NamedArgumentContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#parameterRedefinition.
    def visitParameterRedefinition(self, ctx:KerMLParser.ParameterRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#bodyExpression.
    def visitBodyExpression(self, ctx:KerMLParser.BodyExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#expressionBodyMember.
    def visitExpressionBodyMember(self, ctx:KerMLParser.ExpressionBodyMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#expressionBody.
    def visitExpressionBody(self, ctx:KerMLParser.ExpressionBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalExpression.
    def visitLiteralExpression(self, ctx:KerMLParser.LiteralExpressionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalBoolean.
    def visitLiteralBoolean(self, ctx:KerMLParser.LiteralBooleanContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#booleanValue.
    def visitBooleanValue(self, ctx:KerMLParser.BooleanValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalString.
    def visitLiteralString(self, ctx:KerMLParser.LiteralStringContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalInteger.
    def visitLiteralInteger(self, ctx:KerMLParser.LiteralIntegerContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalReal.
    def visitLiteralReal(self, ctx:KerMLParser.LiteralRealContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#realValue.
    def visitRealValue(self, ctx:KerMLParser.RealValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#literalInfinity.
    def visitLiteralInfinity(self, ctx:KerMLParser.LiteralInfinityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#interaction.
    def visitInteraction(self, ctx:KerMLParser.InteractionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flow.
    def visitFlow(self, ctx:KerMLParser.FlowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#successionFlow.
    def visitSuccessionFlow(self, ctx:KerMLParser.SuccessionFlowContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#itemFlowDeclaration.
    def visitItemFlowDeclaration(self, ctx:KerMLParser.ItemFlowDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#payloadFeatureMember.
    def visitPayloadFeatureMember(self, ctx:KerMLParser.PayloadFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#payloadFeature.
    def visitPayloadFeature(self, ctx:KerMLParser.PayloadFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#payloadFeatureSpecializationPart.
    def visitPayloadFeatureSpecializationPart(self, ctx:KerMLParser.PayloadFeatureSpecializationPartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flowEndMember.
    def visitFlowEndMember(self, ctx:KerMLParser.FlowEndMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flowEnd.
    def visitFlowEnd(self, ctx:KerMLParser.FlowEndContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flowFeatureMember.
    def visitFlowFeatureMember(self, ctx:KerMLParser.FlowFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flowFeature.
    def visitFlowFeature(self, ctx:KerMLParser.FlowFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#flowFeatureRedefinition.
    def visitFlowFeatureRedefinition(self, ctx:KerMLParser.FlowFeatureRedefinitionContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#valuePart.
    def visitValuePart(self, ctx:KerMLParser.ValuePartContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#featureValue.
    def visitFeatureValue(self, ctx:KerMLParser.FeatureValueContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicity.
    def visitMultiplicity(self, ctx:KerMLParser.MultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicitySubset.
    def visitMultiplicitySubset(self, ctx:KerMLParser.MultiplicitySubsetContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicityRange.
    def visitMultiplicityRange(self, ctx:KerMLParser.MultiplicityRangeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedMultiplicity.
    def visitOwnedMultiplicity(self, ctx:KerMLParser.OwnedMultiplicityContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#ownedMultiplicityRange.
    def visitOwnedMultiplicityRange(self, ctx:KerMLParser.OwnedMultiplicityRangeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicityBounds.
    def visitMultiplicityBounds(self, ctx:KerMLParser.MultiplicityBoundsContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#multiplicityExpressionMember.
    def visitMultiplicityExpressionMember(self, ctx:KerMLParser.MultiplicityExpressionMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metaclass.
    def visitMetaclass(self, ctx:KerMLParser.MetaclassContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#prefixMetadataAnnotation.
    def visitPrefixMetadataAnnotation(self, ctx:KerMLParser.PrefixMetadataAnnotationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#prefixMetadataMember.
    def visitPrefixMetadataMember(self, ctx:KerMLParser.PrefixMetadataMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#prefixMetadataFeature.
    def visitPrefixMetadataFeature(self, ctx:KerMLParser.PrefixMetadataFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataFeature.
    def visitMetadataFeature(self, ctx:KerMLParser.MetadataFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataFeatureDeclaration.
    def visitMetadataFeatureDeclaration(self, ctx:KerMLParser.MetadataFeatureDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataBody.
    def visitMetadataBody(self, ctx:KerMLParser.MetadataBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataBodyElement.
    def visitMetadataBodyElement(self, ctx:KerMLParser.MetadataBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataBodyFeatureMember.
    def visitMetadataBodyFeatureMember(self, ctx:KerMLParser.MetadataBodyFeatureMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#metadataBodyFeature.
    def visitMetadataBodyFeature(self, ctx:KerMLParser.MetadataBodyFeatureContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#package.
    def visitPackage(self, ctx:KerMLParser.PackageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#libraryPackage.
    def visitLibraryPackage(self, ctx:KerMLParser.LibraryPackageContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#packageDeclaration.
    def visitPackageDeclaration(self, ctx:KerMLParser.PackageDeclarationContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#packageBody.
    def visitPackageBody(self, ctx:KerMLParser.PackageBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#elementFilterMember.
    def visitElementFilterMember(self, ctx:KerMLParser.ElementFilterMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#view.
    def visitView(self, ctx:KerMLParser.ViewContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#viewBody.
    def visitViewBody(self, ctx:KerMLParser.ViewBodyContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#viewBodyElement.
    def visitViewBodyElement(self, ctx:KerMLParser.ViewBodyElementContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#expose.
    def visitExpose(self, ctx:KerMLParser.ExposeContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#viewRenderingMember.
    def visitViewRenderingMember(self, ctx:KerMLParser.ViewRenderingMemberContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#rendering.
    def visitRendering(self, ctx:KerMLParser.RenderingContext):
        return self.visitChildren(ctx)


    # Visit a parse tree produced by KerMLParser#viewpoint.
    def visitViewpoint(self, ctx:KerMLParser.ViewpointContext):
        return self.visitChildren(ctx)



del KerMLParser